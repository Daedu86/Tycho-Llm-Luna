# Nodes experiment harness

Tycho can act as the deterministic empirical gate for a Nodes workload without taking ownership of the Nodes project, session, Codex authentication, or workspace mapping.

## Boundary

- **Nodes** owns the project map, workload node, primary session, artifacts, and promotion history.
- **Luna/Codex** is the actor that proposes and implements an experiment inside the runner-owned workspace.
- **Tycho** executes the declared Python experiment inside its existing network-disabled Docker/Finch sandbox and returns a structured `promote`, `reject`, or `blocked` decision.
- The experiment protocol cannot select the container runtime/image, inject environment variables, run shell command strings, or escape the configured workspace.

## Runner setup

Install Tycho in the same environment that launches the Nodes Codex Runner:

```bash
python -m pip install -e /path/to/Tycho-Llm-Luna
make -C /path/to/Tycho-Llm-Luna sandbox-image

tycho-experiment --doctor
```

`--doctor` requires an isolated Docker/Finch runtime. `TYCHO_SANDBOX_RUNTIME=host` is intentionally rejected by `tycho-experiment`.

## Protocol

The actor writes a protocol such as `.nodes/tycho-experiment.json` and a Python experiment script inside the current repository:

```json
{
  "schemaVersion": 1,
  "experimentId": "candidate-001",
  "objective": "Beat the current champion under the predeclared robust validation gate.",
  "hypothesis": {
    "statement": "The candidate improves robust validation without increasing variance.",
    "expectedObservation": "The metric clears the promotion threshold on the declared validation protocol.",
    "falsifiers": ["The lift disappears on confirmation splits."]
  },
  "budget": {"maxSteps": 3, "maxWallSeconds": 300, "maxOutputChars": 12000},
  "steps": [
    {
      "id": "verify",
      "script": ".nodes/experiment.py",
      "args": ["--output", ".nodes/metrics.json"],
      "timeoutSeconds": 120,
      "checks": [
        {"kind": "exit_code", "equals": 0},
        {"kind": "json_metric", "file": ".nodes/metrics.json", "path": "metrics.robust_accuracy", "op": ">=", "value": 0.84}
      ]
    }
  ],
  "promotion": {"requireAllSteps": true, "minPassedSteps": 1}
}
```

Execute it with:

```bash
tycho-experiment \
  --workspace . \
  --protocol .nodes/tycho-experiment.json \
  --result .nodes/tycho-result.json
```

The result JSON is replayable experiment evidence. Nodes should attach both the protocol and the result to the workload session before promoting a candidate.
