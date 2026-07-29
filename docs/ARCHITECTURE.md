# Architecture

Tycho separates score-affecting policy from model transport and run operations.

## Core Components

- `tycho/agent`: actor, builder, orchestration modes, context retention, and vision profiles.
- `tycho/prompts`: rendered actor, builder, boundary, and meta-reflection prompts.
- `tycho/workspace`: durable evidence, tools, executable world-model interface, verifier, planner,
  and causal file versioning.
- `tycho/harness`: ARC engine interaction, reset/terminal/animation evidence, scoring, exact resume,
  supervision, status tracking, and scorecard replay.
- `tycho/serving`: provider-neutral tool protocol plus Anthropic Messages, OpenAI Responses, and
  OpenAI-compatible Chat Completions transports.
- `tycho/viewer`: local replay and run-status inspection over recorded evidence; it does not affect
  action selection or scoring.

## Executable Model

An optional `world_model.py` defines `State`, `init_state`, `transition`, `render`, and `outcome`,
with optional `actions`, `subgoals`, and `heuristic`. `render` may use `-1` only for genuinely
unknown cells. The verifier reports exact prediction, known-cell accuracy, and prediction coverage;
the planner searches only goals represented in the current model. The model is advisory: the actor
can keep exploring or reason directly.

## Extension Points

The agent imports only `tycho.serving.llm_client`. Additional transports can implement the same
interface through `TYCHO_LLM_PLUGIN`; worker placement and operational metadata can be extended
through `TYCHO_RUNNER_PLUGIN`. Neither extension point changes prompts, action policy, or scoring.

## Integrity and Isolation

`PUBLIC_RELEASE_MANIFEST.json` records a SHA-256 digest for every tracked file. The validation suite
checks those digests, scans text files for likely credentials, resolves every paper configuration,
runs the test suite, and verifies the built wheel. Agent-authored Python and executable-model replay
run in fresh Docker- or Finch-managed containers. Each container has no network, a read-only root
filesystem, bounded CPU, memory, processes, and captured output, and only the active game workspace
is mounted from the host. The workspace remains writable so the actor can maintain its model and
evidence.
