# Reproducing the Paper Runs

## Scope

The paper reports one stochastic trajectory per policy over all 25 public ARC-AGI-3 games. Exact
action traces are not expected to reproduce bit-for-bit: hosted model sampling, provider revisions,
latency, and retry timing can change a trajectory. The artifact instead fixes the score-affecting
Tycho policy, prompts, tool schemas, evidence flow, budgets, and scoring code.

Tycho includes native Anthropic and OpenAI transports. Compact manifests for the reported official
competition-mode scorecards are available under `artifacts/scorecards/`.

## Setup

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'
export ARC_API_KEY=...
make sandbox-image
make sandbox-check
```

The sandbox uses Docker or Finch and automatically selects an available runtime. On macOS it
prefers Finch; elsewhere it checks Docker first. Use `TYCHO_SANDBOX_RUNTIME=docker` or `finch` for an
explicit choice. `TYCHO_SANDBOX_RUNTIME=host` is available only for trusted development and unit
tests; it should not be used for benchmark evaluation.

For persistent local credentials, copy `.env.example` to the ignored `.env`, fill only the keys you
need, and load it into the current shell. Tycho does not read credential files implicitly.

```bash
cp .env.example .env
chmod 600 .env
set -a; source .env; set +a
```

For Claude:

```bash
export ANTHROPIC_API_KEY=...
CONFIG=configs/paper/opus48_orchestrator.yaml
```

For the Opus 5 selected-policy run, use
`CONFIG=configs/paper/opus5_orchestrator.yaml`.

For GPT:

```bash
export OPENAI_API_KEY=...
CONFIG=configs/paper/gpt56_sol_orchestrator_max.yaml
```

## Validation Ladder

Run the credential-free gate first. It makes no Anthropic, OpenAI, or ARC requests:

```bash
make validate
```

It runs the unit and contract suite, validates all paper configs with fake credentials, verifies
every repository-manifest hash, scans text files for likely secrets, builds a wheel, and checks that
prompts and workspace templates were packaged.

Next, test one native model transport. This sends exactly one paid text+image+tool request and
requires an explicit acknowledgement:

```bash
LLM_BACKEND=anthropic LLM_MODEL=<anthropic-model-id> \
  .venv/bin/python scripts/smoke_provider.py --confirm-paid-call

LLM_BACKEND=openai_responses LLM_MODEL=<openai-model-id> \
  .venv/bin/python scripts/smoke_provider.py --confirm-paid-call
```

The transport smoke disables provider reasoning controls by default so it also works with small
models that do not implement those controls. Pass `--effort low` (or a higher supported value) only
when deliberately testing reasoning configuration for a specific model.

Finally, a bounded game smoke uses direct reasoning, disables animation-summary calls, permits at
most two model calls, and has a $0.50 public-list cost guard. A single call can cross a cost guard,
so the two-call ceiling is the hard safety bound.

```bash
TYCHO_MAX_LLM_CALLS=2 TYCHO_MAX_TOOL_STEPS=2 \
TYCHO_MAX_INFERENCE_COST_PER_GAME=0.50 TYCHO_ANIMATION_SUMMARY=0 \
.venv/bin/python -m tycho.harness.run_parallel \
  --approach tycho --games tr87 --out-dir results/smoke \
  --config configs/smoke/minimal.yaml --max-workers 1
```

The explicit environment values are intentional: environment variables take precedence over config
files, so these four safety bounds cannot be weakened by values left in the shell from a prior run.

Inspect the bounded smoke before scaling up:

```bash
tycho-viewer results --host 127.0.0.1 --port 8900
```

Open `http://127.0.0.1:8900/` for the replay and `http://127.0.0.1:8900/status` for run status.
The underlying `results/smoke/manifest.json`, `game_tr87.json`, and `status/tr87/status.json` remain
plain JSON for independent analysis.

Run all public games by passing their identifiers to `--games`. A full run should use one process
per game subject to provider capacity. Start with one smoke game and then increase `--max-workers`.

```bash
.venv/bin/python -m tycho.harness.run_parallel \
  --approach tycho \
  --games ar25,bp35,cd82,cn04,dc22,ft09,g50t,ka59,lf52,lp85,ls20,m0r0,r11l,re86,s5i5,sb26,sc25,sk48,sp80,su15,tn36,tr87,tu93,vc33,wa30 \
  --out-dir results/reproduction \
  --config "$CONFIG" \
  --operation-mode offline \
  --max-workers 8 \
  --auto-resume
```

The reported runs used ARC-AGI-3's cached offline engine. Populate its public environment cache
before using `--operation-mode offline`. The runner writes one game record at a time,
`manifest.json`, immutable `run_spec.json`, per-game status, durable workspaces, and exact
checkpoints. A failed game can be resumed independently:

```bash
.venv/bin/python -m tycho.harness.run_parallel \
  --approach tycho --out-dir results/reproduction --config "$CONFIG" \
  --resume --resume-games bp35
```

Shareable run artifacts contain the public model identity, API protocol, stable configuration, and
error categories. For full local worker output and tracebacks, set `TYCHO_DIAGNOSTICS_DIR` to a
directory outside the run output before launch.

## Verification

```bash
.venv/bin/python -m tycho.harness.planner_follow_diagnostics results/reproduction
```

Official scorecards require replaying recorded actions in ARC-AGI-3 competition mode. The replay
tool is intentionally separate from model inference so interrupted runs can be repaired before a
scorecard is created:

```bash
.venv/bin/python -m tycho.harness.submission_replay --help
```

Keep API keys in the ignored `.env` file or in the process environment. Run directories are ignored
by default; review them for credentials before sharing them.
