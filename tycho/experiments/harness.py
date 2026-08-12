"""Deterministic, sandboxed execution and falsification loop for generic Tycho experiments."""
from __future__ import annotations

import json
import math
import operator
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from tycho.workspace.sandbox import PythonSandbox, SandboxError, SandboxResult

from .protocol import Check, ExperimentProtocol, ProtocolError, resolve_inside_workspace


@dataclass(frozen=True)
class CheckResult:
    kind: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class StepResult:
    id: str
    status: str
    script: str
    args: list[str]
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    checks: list[CheckResult]
    error: str | None = None


class ExperimentSandbox(Protocol):
    runtime: str
    image: str

    def check(self, *, require_isolation: bool = False) -> dict: ...

    def run_script(
        self,
        workspace: str | Path,
        script: str | Path,
        *,
        timeout: int | float,
        args: tuple[str, ...] = (),
    ) -> SandboxResult: ...


_COMPARATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "\n[output truncated by Tycho experiment budget]"
    keep = max(0, limit - len(marker))
    return value[:keep] + marker


def _read_json_path(path: Path, dotted_path: str) -> Any:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    for key in dotted_path.split("."):
        if not key:
            raise KeyError("empty json path segment")
        if isinstance(value, list):
            value = value[int(key)]
        elif isinstance(value, dict):
            value = value[key]
        else:
            raise KeyError(key)
    return value


def _evaluate_check(
    check: Check,
    *,
    exit_code: int,
    stdout: str,
    stderr: str,
    workspace: Path,
) -> CheckResult:
    if check.kind == "exit_code":
        passed = exit_code == check.equals
        return CheckResult("exit_code", passed, f"exit code {exit_code}; expected {check.equals}")

    if check.kind == "stdout_contains":
        needle = str(check.value)
        passed = needle in stdout
        return CheckResult("stdout_contains", passed, f"stdout contains {needle!r}: {passed}")

    if check.kind == "stderr_not_contains":
        needle = str(check.value)
        passed = needle not in stderr
        return CheckResult("stderr_not_contains", passed, f"stderr excludes {needle!r}: {passed}")

    if check.kind == "json_metric":
        assert check.file is not None and check.path is not None and check.op is not None
        metric_path = resolve_inside_workspace(workspace, check.file, "json_metric.file")
        try:
            actual = _read_json_path(metric_path, check.path)
        except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
            return CheckResult("json_metric", False, f"unable to read {check.file}:{check.path}: {exc}")
        expected = check.value
        if check.op in {">", ">=", "<", "<="}:
            if (
                isinstance(actual, bool)
                or not isinstance(actual, (int, float))
                or not math.isfinite(float(actual))
            ):
                return CheckResult(
                    "json_metric",
                    False,
                    f"metric {check.path} is not a finite number: {actual!r}",
                )
            assert isinstance(expected, (int, float)) and not isinstance(expected, bool)
            expected_number = float(expected)
            passed = bool(_COMPARATORS[check.op](float(actual), expected_number))
            return CheckResult(
                "json_metric",
                passed,
                f"{check.file}:{check.path} = {actual} {check.op} {expected_number}: {passed}",
            )

        if isinstance(expected, bool):
            comparable = isinstance(actual, bool)
        elif isinstance(expected, str):
            comparable = isinstance(actual, str)
        elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
            comparable = (
                isinstance(actual, (int, float))
                and not isinstance(actual, bool)
                and math.isfinite(float(actual))
            )
            if comparable:
                actual = float(actual)
                expected = float(expected)
        else:
            comparable = False

        if not comparable:
            return CheckResult(
                "json_metric",
                False,
                f"metric {check.path} type {type(actual).__name__} is incompatible with expected {expected!r}",
            )
        passed = bool(_COMPARATORS[check.op](actual, expected))
        return CheckResult(
            "json_metric",
            passed,
            f"{check.file}:{check.path} = {actual!r} {check.op} {expected!r}: {passed}",
        )

    return CheckResult(str(check.kind), False, "unsupported check kind")


def run_experiment(
    protocol: ExperimentProtocol,
    workspace: Path,
    *,
    sandbox: ExperimentSandbox | None = None,
    verify_sandbox: bool = True,
) -> dict[str, Any]:
    root = workspace.resolve()
    if not root.is_dir():
        raise ProtocolError(f"workspace does not exist or is not a directory: {root}")

    executor = sandbox or PythonSandbox()
    if executor.runtime == "host":
        raise ProtocolError(
            "Tycho experiments require an isolated Docker/Finch runtime; host execution is disabled"
        )
    if verify_sandbox:
        executor.check(require_isolation=True)

    started_at = _utc_now()
    started_clock = time.monotonic()
    results: list[StepResult] = []
    stop_reason: str | None = None

    for index, step in enumerate(protocol.steps):
        elapsed = time.monotonic() - started_clock
        if index >= protocol.budget.max_steps:
            stop_reason = "step_budget_exhausted"
            break
        if elapsed >= protocol.budget.max_wall_seconds:
            stop_reason = "wall_clock_budget_exhausted"
            break

        script = resolve_inside_workspace(root, step.script, f"step[{step.id}].script")
        if not script.is_file():
            results.append(
                StepResult(
                    id=step.id,
                    status="blocked",
                    script=step.script,
                    args=list(step.args),
                    exit_code=None,
                    duration_seconds=0.0,
                    stdout="",
                    stderr="",
                    checks=[],
                    error="experiment script does not exist or is not a file",
                )
            )
            continue

        remaining_wall = max(1, int(protocol.budget.max_wall_seconds - elapsed))
        timeout = min(step.timeout_seconds, remaining_wall)
        step_started = time.monotonic()
        try:
            completed = executor.run_script(root, script, timeout=timeout, args=step.args)
            duration = time.monotonic() - step_started
            stdout = _truncate(completed.stdout or "", protocol.budget.max_output_chars)
            stderr = _truncate(completed.stderr or "", protocol.budget.max_output_chars)
            if completed.timed_out:
                results.append(
                    StepResult(
                        id=step.id,
                        status="blocked",
                        script=step.script,
                        args=list(step.args),
                        exit_code=None,
                        duration_seconds=round(duration, 6),
                        stdout=stdout,
                        stderr=stderr,
                        checks=[],
                        error=f"step exceeded {timeout}s timeout",
                    )
                )
                continue

            checks = [
                _evaluate_check(
                    check,
                    exit_code=completed.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    workspace=root,
                )
                for check in step.checks
            ]
            passed = all(result.passed for result in checks) if checks else completed.returncode == 0
            results.append(
                StepResult(
                    id=step.id,
                    status="passed" if passed else "failed",
                    script=step.script,
                    args=list(step.args),
                    exit_code=completed.returncode,
                    duration_seconds=round(duration, 6),
                    stdout=stdout,
                    stderr=stderr,
                    checks=checks,
                )
            )
        except (OSError, SandboxError) as exc:
            duration = time.monotonic() - step_started
            results.append(
                StepResult(
                    id=step.id,
                    status="blocked",
                    script=step.script,
                    args=list(step.args),
                    exit_code=None,
                    duration_seconds=round(duration, 6),
                    stdout="",
                    stderr="",
                    checks=[],
                    error=str(exc),
                )
            )

    passed_steps = sum(result.status == "passed" for result in results)
    failed_steps = sum(result.status == "failed" for result in results)
    blocked_steps = sum(result.status == "blocked" for result in results)
    all_executed = len(results) == len(protocol.steps)
    required_passed = passed_steps >= protocol.promotion.min_passed_steps
    all_passed = all_executed and failed_steps == 0 and blocked_steps == 0

    if stop_reason or blocked_steps:
        decision = "blocked"
    elif protocol.promotion.require_all_steps:
        decision = "promote" if all_passed and required_passed else "reject"
    else:
        decision = "promote" if required_passed else "reject"

    wall_seconds = round(time.monotonic() - started_clock, 6)
    return {
        "schemaVersion": 1,
        "experimentId": protocol.experiment_id,
        "objective": protocol.objective,
        "hypothesis": {
            "statement": protocol.hypothesis.statement,
            "expectedObservation": protocol.hypothesis.expected_observation,
            "falsifiers": list(protocol.hypothesis.falsifiers),
        },
        "decision": decision,
        "startedAt": started_at,
        "finishedAt": _utc_now(),
        "sandbox": {"runtime": executor.runtime, "image": executor.image},
        "budget": {
            "maxSteps": protocol.budget.max_steps,
            "stepsUsed": len(results),
            "maxWallSeconds": protocol.budget.max_wall_seconds,
            "wallSeconds": wall_seconds,
            "stopReason": stop_reason,
        },
        "summary": {
            "stepCount": len(protocol.steps),
            "executedSteps": len(results),
            "passedSteps": passed_steps,
            "failedSteps": failed_steps,
            "blockedSteps": blocked_steps,
            "requireAllSteps": protocol.promotion.require_all_steps,
            "minPassedSteps": protocol.promotion.min_passed_steps,
        },
        "steps": [
            {
                **{k: v for k, v in asdict(result).items() if k != "checks"},
                "checks": [asdict(check) for check in result.checks],
            }
            for result in results
        ],
        "metadata": dict(protocol.metadata),
    }
