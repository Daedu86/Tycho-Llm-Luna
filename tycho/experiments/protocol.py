"""Validated protocol for Tycho's generic experiment harness.

The protocol is intentionally independent from ARC. An external actor such as
Nodes + Luna/Codex can declare a falsifiable experiment, but it cannot choose a
host executable, a container image, a network policy, or a filesystem path
outside the configured workspace. Experiment code is a Python script inside the
workspace and execution is delegated to Tycho's existing isolated PythonSandbox.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


CheckKind = Literal[
    "exit_code",
    "stdout_contains",
    "stderr_not_contains",
    "json_metric",
]
MetricOperator = Literal[">", ">=", "<", "<=", "==", "!="]


class ProtocolError(ValueError):
    """Raised when an experiment protocol violates the harness contract."""


def _record(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{path} must be an object")
    return value


def _text(value: Any, path: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"{path} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, path: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProtocolError(f"{path} must be a positive integer")
    return value


def _string_list(value: Any, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProtocolError(f"{path} must be an array of strings")
    return [_text(item, f"{path}[{index}]") for index, item in enumerate(value)]


@dataclass(frozen=True)
class Hypothesis:
    statement: str
    expected_observation: str
    falsifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Budget:
    max_steps: int = 8
    max_wall_seconds: int = 600
    max_output_chars: int = 12_000


@dataclass(frozen=True)
class Check:
    kind: CheckKind
    equals: int | None = None
    value: str | float | int | bool | None = None
    file: str | None = None
    path: str | None = None
    op: MetricOperator | None = None


@dataclass(frozen=True)
class Step:
    id: str
    script: str
    args: tuple[str, ...] = ()
    timeout_seconds: int = 120
    checks: tuple[Check, ...] = ()


@dataclass(frozen=True)
class Promotion:
    require_all_steps: bool = True
    min_passed_steps: int = 1


@dataclass(frozen=True)
class ExperimentProtocol:
    schema_version: int
    experiment_id: str
    objective: str
    hypothesis: Hypothesis
    budget: Budget
    steps: tuple[Step, ...]
    promotion: Promotion
    metadata: dict[str, Any] = field(default_factory=dict)


def _parse_check(value: Any, path: str) -> Check:
    raw = _record(value, path)
    kind = _text(raw.get("kind"), f"{path}.kind")
    if kind not in {"exit_code", "stdout_contains", "stderr_not_contains", "json_metric"}:
        raise ProtocolError(f"{path}.kind is not supported: {kind}")

    if kind == "exit_code":
        equals = raw.get("equals", 0)
        if isinstance(equals, bool) or not isinstance(equals, int):
            raise ProtocolError(f"{path}.equals must be an integer")
        return Check(kind="exit_code", equals=equals)

    if kind in {"stdout_contains", "stderr_not_contains"}:
        return Check(kind=kind, value=_text(raw.get("value"), f"{path}.value"))  # type: ignore[arg-type]

    metric_file = _text(raw.get("file"), f"{path}.file")
    metric_path = _text(raw.get("path"), f"{path}.path")
    op = _text(raw.get("op"), f"{path}.op")
    if op not in {">", ">=", "<", "<=", "==", "!="}:
        raise ProtocolError(f"{path}.op is not supported: {op}")
    target = raw.get("value")
    if op in {">", ">=", "<", "<="}:
        if isinstance(target, bool) or not isinstance(target, (int, float)):
            raise ProtocolError(f"{path}.value must be numeric for ordered json_metric comparisons")
    elif not isinstance(target, (str, int, float, bool)):
        raise ProtocolError(f"{path}.value must be a scalar for json_metric equality comparisons")
    return Check(
        kind="json_metric",
        file=metric_file,
        path=metric_path,
        op=op,  # type: ignore[arg-type]
        value=target,
    )


def _parse_step(value: Any, path: str) -> Step:
    raw = _record(value, path)
    step_id = _text(raw.get("id"), f"{path}.id")
    script = _text(raw.get("script"), f"{path}.script")
    if not script.lower().endswith(".py"):
        raise ProtocolError(f"{path}.script must reference a Python .py file")
    args = tuple(_string_list(raw.get("args"), f"{path}.args"))
    checks_raw = raw.get("checks", [])
    if not isinstance(checks_raw, list):
        raise ProtocolError(f"{path}.checks must be an array")
    checks = tuple(_parse_check(item, f"{path}.checks[{index}]") for index, item in enumerate(checks_raw))
    return Step(
        id=step_id,
        script=script,
        args=args,
        timeout_seconds=_positive_int(raw.get("timeoutSeconds"), f"{path}.timeoutSeconds", 120),
        checks=checks,
    )


def parse_protocol(value: Any) -> ExperimentProtocol:
    raw = _record(value, "protocol")
    version = raw.get("schemaVersion")
    if version != 1:
        raise ProtocolError("protocol.schemaVersion must equal 1")

    hypothesis_raw = _record(raw.get("hypothesis"), "protocol.hypothesis")
    hypothesis = Hypothesis(
        statement=_text(hypothesis_raw.get("statement"), "protocol.hypothesis.statement"),
        expected_observation=_text(
            hypothesis_raw.get("expectedObservation"),
            "protocol.hypothesis.expectedObservation",
        ),
        falsifiers=tuple(_string_list(hypothesis_raw.get("falsifiers"), "protocol.hypothesis.falsifiers")),
    )

    budget_raw = _record(raw.get("budget", {}), "protocol.budget")
    budget = Budget(
        max_steps=_positive_int(budget_raw.get("maxSteps"), "protocol.budget.maxSteps", 8),
        max_wall_seconds=_positive_int(
            budget_raw.get("maxWallSeconds"), "protocol.budget.maxWallSeconds", 600
        ),
        max_output_chars=_positive_int(
            budget_raw.get("maxOutputChars"), "protocol.budget.maxOutputChars", 12_000
        ),
    )

    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ProtocolError("protocol.steps must be a non-empty array")
    steps = tuple(_parse_step(item, f"protocol.steps[{index}]") for index, item in enumerate(steps_raw))
    ids = [step.id for step in steps]
    if len(ids) != len(set(ids)):
        raise ProtocolError("protocol.steps ids must be unique")
    if len(steps) > budget.max_steps:
        raise ProtocolError("protocol defines more steps than budget.maxSteps")

    promotion_raw = _record(raw.get("promotion", {}), "protocol.promotion")
    min_passed = _positive_int(
        promotion_raw.get("minPassedSteps"),
        "protocol.promotion.minPassedSteps",
        len(steps),
    )
    if min_passed > len(steps):
        raise ProtocolError("protocol.promotion.minPassedSteps cannot exceed step count")

    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ProtocolError("protocol.metadata must be an object")

    return ExperimentProtocol(
        schema_version=1,
        experiment_id=_text(raw.get("experimentId"), "protocol.experimentId"),
        objective=_text(raw.get("objective"), "protocol.objective"),
        hypothesis=hypothesis,
        budget=budget,
        steps=steps,
        promotion=Promotion(
            require_all_steps=bool(promotion_raw.get("requireAllSteps", True)),
            min_passed_steps=min_passed,
        ),
        metadata=dict(metadata),
    )


def resolve_inside_workspace(workspace: Path, relative: str, field: str) -> Path:
    """Resolve a protocol path and reject any attempt to leave the workspace."""
    path = Path(relative)
    if path.is_absolute():
        raise ProtocolError(f"{field} must be relative to the configured workspace")
    candidate = (workspace / path).resolve()
    root = workspace.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProtocolError(f"{field} escapes the configured workspace") from exc
    return candidate
