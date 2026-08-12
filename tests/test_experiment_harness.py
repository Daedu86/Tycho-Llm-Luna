from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tycho.experiments.harness import run_experiment
from tycho.experiments.protocol import ProtocolError, parse_protocol, resolve_inside_workspace


@dataclass
class FakeResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


class TestSandbox:
    runtime = "docker"
    image = "test-sandbox"

    def check(self, *, require_isolation: bool = False):
        assert require_isolation is True
        return {"runtime": self.runtime, "image": self.image}

    def run_script(self, workspace, script, *, timeout, args=()):
        result = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return FakeResult(result.stdout, result.stderr, result.returncode)


def protocol(metric_threshold: float = 0.84):
    return {
        "schemaVersion": 1,
        "experimentId": "candidate-1",
        "objective": "Improve robust accuracy.",
        "hypothesis": {
            "statement": "The candidate improves validation.",
            "expectedObservation": "robust_accuracy clears the gate",
            "falsifiers": ["metric misses the predeclared gate"],
        },
        "budget": {"maxSteps": 2, "maxWallSeconds": 30, "maxOutputChars": 2000},
        "steps": [
            {
                "id": "verify",
                "script": "experiment.py",
                "args": ["metrics.json"],
                "timeoutSeconds": 10,
                "checks": [
                    {"kind": "exit_code", "equals": 0},
                    {
                        "kind": "json_metric",
                        "file": "metrics.json",
                        "path": "metrics.robust_accuracy",
                        "op": ">=",
                        "value": metric_threshold,
                    },
                ],
            }
        ],
        "promotion": {"requireAllSteps": True, "minPassedSteps": 1},
    }


def write_experiment(root: Path, value: float):
    (root / "experiment.py").write_text(
        "import json, pathlib, sys\n"
        f"pathlib.Path(sys.argv[1]).write_text(json.dumps({{'metrics': {{'robust_accuracy': {value}}}}}))\n"
        "print('experiment-finished')\n",
        encoding="utf-8",
    )


def test_passing_metric_promotes(tmp_path: Path):
    write_experiment(tmp_path, 0.85)
    result = run_experiment(parse_protocol(protocol()), tmp_path, sandbox=TestSandbox())
    assert result["decision"] == "promote"
    assert result["summary"]["passedSteps"] == 1
    assert result["sandbox"] == {"runtime": "docker", "image": "test-sandbox"}


def test_failed_falsifier_rejects(tmp_path: Path):
    write_experiment(tmp_path, 0.81)
    result = run_experiment(parse_protocol(protocol()), tmp_path, sandbox=TestSandbox())
    assert result["decision"] == "reject"
    assert result["steps"][0]["checks"][1]["passed"] is False


def test_workspace_escape_is_rejected(tmp_path: Path):
    with pytest.raises(ProtocolError, match="escapes"):
        resolve_inside_workspace(tmp_path, "../outside.py", "step.script")


def test_protocol_rejects_shell_commands():
    raw = protocol()
    raw["steps"][0].pop("script")
    raw["steps"][0]["command"] = "python experiment.py"
    with pytest.raises(ProtocolError, match="script"):
        parse_protocol(raw)


def test_protocol_enforces_step_budget():
    raw = protocol()
    raw["budget"]["maxSteps"] = 1
    raw["steps"].append({**raw["steps"][0], "id": "second"})
    with pytest.raises(ProtocolError, match="maxSteps"):
        parse_protocol(raw)


def test_host_runtime_is_never_accepted(tmp_path: Path):
    write_experiment(tmp_path, 0.85)
    sandbox = TestSandbox()
    sandbox.runtime = "host"
    with pytest.raises(ProtocolError, match="require an isolated"):
        run_experiment(parse_protocol(protocol()), tmp_path, sandbox=sandbox)
