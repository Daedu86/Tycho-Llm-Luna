# L0 vs L1 ARC-AGI-3 diagnostic benchmark

This experiment measures the effect of **L1 semantic grounding** while holding the Tycho/Luna policy constant.

## Why a diagnostic subset

The published Tycho GPT-5.6 Sol public-set result already reaches the ARC-AGI-3 RHAE ceiling, so a full 25-game score-only A/B test has weak sensitivity. The first L0/L1 experiment therefore uses five public games with substantial interaction cost or useful reasoning diversity:

- `bp35` — high action count and multiple resets in the published GPT-5.6 Sol run.
- `dc22` — very high action count; useful for testing whether stable perceptual structure reduces wasted interaction.
- `lf52` — long multi-level trajectory with substantial action cost.
- `ls20` — documented ARC-AGI-3 agent-reasoning example and a nontrivial Tycho trajectory.
- `vc33` — documented ARC-AGI-3 orchestration example.

Frozen game list:

```text
bp35,dc22,lf52,ls20,vc33
```

## Controlled variables

Run L0 and L1 from the **same** `architecture/epistemic-neurosymbolic` revision. Only `--approach` changes.

Keep fixed:

- Codex/Luna transport (`tycho.serving.codex_luna_plugin`)
- model (`gpt-5.6-luna`)
- Tycho mode (`orchestrator`)
- reasoning effort (`medium`)
- maximum LLM calls (`1100` per game)
- maximum tool steps (`25` per turn)
- animation summary disabled for the first paired run
- same ARC API identity / operation mode
- same game set
- same worker count for both arms

Do not tune either arm after seeing the other arm's result.

## Environment

Git Bash / Linux / macOS:

```bash
export TYCHO_LLM_PLUGIN=tycho.serving.codex_luna_plugin
export LLM_BACKEND=codex
export LLM_MODEL=gpt-5.6-luna
export TYCHO_MODE=orchestrator
export TYCHO_EFFORT=medium
export TYCHO_MAX_LLM_CALLS=1100
export TYCHO_MAX_TOOL_STEPS=25
export TYCHO_ANIMATION_SUMMARY=0
```

PowerShell:

```powershell
$env:TYCHO_LLM_PLUGIN = "tycho.serving.codex_luna_plugin"
$env:LLM_BACKEND = "codex"
$env:LLM_MODEL = "gpt-5.6-luna"
$env:TYCHO_MODE = "orchestrator"
$env:TYCHO_EFFORT = "medium"
$env:TYCHO_MAX_LLM_CALLS = "1100"
$env:TYCHO_MAX_TOOL_STEPS = "25"
$env:TYCHO_ANIMATION_SUMMARY = "0"
```

Run the zero-call preflight before either arm:

```bash
python scripts/codex_preflight.py
```

## L0 — Tycho + Luna

```bash
python -m tycho.harness.run_parallel \
  --approach tycho \
  --games bp35,dc22,lf52,ls20,vc33 \
  --out-dir results/epistemic-l0 \
  --max-workers 1 \
  --viz
```

## L1 — semantic grounding + Luna

```bash
python -m tycho.harness.run_parallel \
  --approach tycho.epistemic.grounded_agent \
  --games bp35,dc22,lf52,ls20,vc33 \
  --out-dir results/epistemic-l1 \
  --max-workers 1 \
  --viz
```

L1 additionally persists `level_<L>/scene_<turn>.json` grounding artifacts.

## Comparison contract

RHAE/completion remain authoritative benchmark outcomes, but the public-set ceiling means the first architectural comparison must also retain process metrics.

For every game compare:

1. completion and RHAE;
2. total scored actions and per-level actions;
3. resets / game-over events;
4. LLM calls, input/output/cache tokens, and inference cost when available;
5. final world-model simulation accuracy / verification diagnostics;
6. no-op or repeated-action behavior;
7. builder invocations / model repairs;
8. for L1, grounding entity/property/relation/event counts and `scene_*.json` stability;
9. qualitative cases where grounding helped, distracted, or was ignored.

Primary architectural success is **not** required to be a higher capped RHAE. L1 is viable for L2 if it preserves task performance while producing stable, useful semantic evidence at acceptable action/token overhead. Any regression must be explained at the per-game level before proceeding.

## L2 gate

Proceed to a persistent `BeliefState` only after the paired report answers:

- Are grounding artifacts stable enough to accumulate across turns?
- Does L1 preserve or improve completion/action efficiency?
- Is token/call overhead acceptable?
- Do traces show at least one credible mechanism by which grounding improves interpretation or recovery?
- Are observed regressions fixable in grounding rather than signs that the layer is unnecessary?

The Nodes project **Tycho Epistemic — L0 vs L1 ARC-AGI-3 Benchmark** mirrors this experiment as six workload nodes: benchmark contract, L0 run, L1 run, diagnostics, paired comparison, and the L2 decision gate.
