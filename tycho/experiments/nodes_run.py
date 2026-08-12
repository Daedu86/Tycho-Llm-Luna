"""CLI entry point for the generic Tycho experiment harness used by Nodes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from tycho.workspace.sandbox import PythonSandbox, SandboxError

from .harness import run_experiment
from .protocol import ProtocolError, parse_protocol, resolve_inside_workspace


EXAMPLE_PROTOCOL = {
    "schemaVersion": 1,
    "experimentId": "candidate-001",
    "objective": "Test one falsifiable improvement against the current champion.",
    "hypothesis": {
        "statement": "The candidate improves robust validation without increasing variance.",
        "expectedObservation": "The verification metric clears the predeclared promotion threshold.",
        "falsifiers": [
            "The candidate improves only one split.",
            "The candidate violates the leakage or reproducibility contract.",
        ],
    },
    "budget": {"maxSteps": 4, "maxWallSeconds": 300, "maxOutputChars": 12000},
    "steps": [
        {
            "id": "verify",
            "script": ".nodes/experiment.py",
            "args": ["--output", ".nodes/metrics.json"],
            "timeoutSeconds": 120,
            "checks": [
                {"kind": "exit_code", "equals": 0},
                {
                    "kind": "json_metric",
                    "file": ".nodes/metrics.json",
                    "path": "metrics.robust_accuracy",
                    "op": ">=",
                    "value": 0.84,
                },
            ],
        }
    ],
    "promotion": {"requireAllSteps": True, "minPassedSteps": 1},
    "metadata": {"source": "nodes"},
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tycho-experiment",
        description="Run a falsifiable experiment protocol in Tycho's isolated Python sandbox.",
    )
    parser.add_argument("--workspace", default=".", help="Trusted experiment workspace root")
    parser.add_argument("--protocol", help="JSON protocol path, resolved inside the workspace")
    parser.add_argument(
        "--result",
        default=".nodes/tycho-result.json",
        help="Result JSON path, resolved inside the workspace",
    )
    parser.add_argument("--doctor", action="store_true", help="Verify the isolated Tycho sandbox and exit")
    parser.add_argument("--print-example", action="store_true", help="Print an example protocol and exit")
    parser.add_argument("--version", action="store_true", help="Print protocol version and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.version:
        print("tycho-experiment protocol-v1")
        return 0
    if args.print_example:
        print(json.dumps(EXAMPLE_PROTOCOL, indent=2, ensure_ascii=False))
        return 0
    if args.doctor:
        try:
            payload = PythonSandbox().check(require_isolation=True)
        except SandboxError as exc:
            print(f"sandbox check failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"ok": True, "runtime": payload.get("runtime"), "image": payload.get("image")}, ensure_ascii=False))
        return 0
    if not args.protocol:
        print("error: --protocol is required unless --doctor, --print-example or --version is used", file=sys.stderr)
        return 2

    workspace = Path(args.workspace).expanduser().resolve()
    try:
        protocol_path = resolve_inside_workspace(workspace, args.protocol, "--protocol")
        result_path = resolve_inside_workspace(workspace, args.result, "--result")
        raw = json.loads(protocol_path.read_text(encoding="utf-8"))
        protocol = parse_protocol(raw)
        result = run_experiment(protocol, workspace)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({
            "experimentId": result["experimentId"],
            "decision": result["decision"],
            "result": str(result_path.relative_to(workspace)),
            "summary": result["summary"],
        }, ensure_ascii=False))
        return 0 if result["decision"] == "promote" else 3 if result["decision"] == "reject" else 4
    except (OSError, ValueError, json.JSONDecodeError, ProtocolError, SandboxError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
