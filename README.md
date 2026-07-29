# Tycho

> *Tycho Brahe never knew the laws of planetary motion. What he did, for decades and by hand, was*
> ***observe***: *he made the most precise records of the heavens anyone had seen. Kepler later*
> *derived the laws from those observations. The method was the insight: the laws of an unknown*
> *world are not handed to you; they are uncovered by watching carefully and refusing to look away.*

**Tycho** is a self-directed agent harness for **ARC-AGI-3**, built around that same empiricist
loop. A multimodal model enters an unfamiliar 64x64 world without rules or an objective. Tycho
preserves what it sees, what it does, and what follows. When useful, the agent turns that evidence
into a free-form executable hypothesis (`State`, `transition`, `render`, and `outcome`), checks the
hypothesis against experience, and plans through it. When formalization is not useful, the agent
remains free to reason directly. Observe, model, act, revise.

This repository contains the implementation and evaluation artifacts for **“Tycho: Active
Abstraction with Programmatic World Models for ARC-AGI-3.”** It includes the agent, prompts,
workspace API, planner and verifier, benchmark runner, Anthropic and OpenAI transports, paper
configurations, replay viewer, tests, and compact scorecard evidence.

## Results

Official ARC-AGI-3 competition-mode scorecards on all 25 public games:

| Policy | Model | RHAE | Scorecard |
|---|---|---:|---|
| No world model | Claude Opus 4.8 | 79.07 | [30bdf730](https://arcprize.org/scorecards/30bdf730-7aaf-49db-aae4-937df15bc5da) |
| Single actor model | Claude Opus 4.8 | 85.36 | [3732640f](https://arcprize.org/scorecards/3732640f-0e6c-44d4-8e2c-bae7c6476fad) |
| Actor-controlled builder | Claude Opus 4.8 | 88.49 | [5477a5f0](https://arcprize.org/scorecards/5477a5f0-efe9-43ae-83c1-cda8426c318c) |
| Falsification-triggered builder | Claude Opus 4.8 | 83.07 | [f31be13c](https://arcprize.org/scorecards/f31be13c-411d-4c32-a6c3-99c0a9c1bdbc) |
| Actor-controlled builder | GPT-5.6 Sol | **100.00** | [18d94e34](https://arcprize.org/scorecards/18d94e34-fee4-4fa9-9433-b6ab76c55554) |
| Actor-controlled builder | Claude Opus 5 | **100.00** | [08b98aa0](https://arcprize.org/scorecards/08b98aa0-5df0-42c0-b501-856f553a21e9) |

The scorecard manifests and aggregate paper metrics are in [`artifacts/`](artifacts/).

## Install

Python 3.12 or newer is required.

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

Equivalently, `make bootstrap` uses `python3`; when that name resolves to an older system Python,
select an installed interpreter explicitly, for example
`make bootstrap BOOTSTRAP_PYTHON=python3.12`.

Agent-authored Python runs in a fresh, network-disabled container. Docker Engine, Docker Desktop,
and Finch are supported through their command-line interfaces:

```bash
make sandbox-image
make sandbox-check
```

Runtime selection is automatic; on macOS Finch is preferred when available. Set
`TYCHO_SANDBOX_RUNTIME=docker` or `finch` to select one explicitly.

Set one model provider:

```bash
export ANTHROPIC_API_KEY=...
# or: export OPENAI_API_KEY=...
```

Before using either key, run the credential-free validation suite:

```bash
make validate
```

This checks tests, configuration resolution, repository-integrity hashes, likely secret leakage,
and the built wheel without calling Anthropic, OpenAI, or ARC. Provider and bounded game smoke tests
are separate, explicit steps in [`docs/REPRODUCING.md`](docs/REPRODUCING.md). Benchmark execution
also checks the container runtime before making a model call. The paper
configurations are long-running, stochastic, and expensive; do not use them as smoke tests.

Inspect completed or in-progress runs with the local replay viewer:

```bash
tycho-viewer results --host 127.0.0.1 --port 8900
```

Open `http://127.0.0.1:8900/` for frame-by-frame evidence, model calls, executable-model
diagnostics, and workspace history. The `/status` page summarizes supervised long-running jobs.

## Four Policies

- `no_world_model`: direct reasoning from typed evidence and durable notes.
- `single`: the actor may write and use `world_model.py` itself.
- `orchestrator`: the actor invokes a focused world-model builder when useful.
- `trigger`: the harness invokes the builder when verification falsifies or under-specifies a model.

The same observation, action, reset, animation, resume, and scoring paths are used in every policy.
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the component boundaries and executable-model
interface.

## License

Apache License 2.0. ARC-AGI-3 environments and engine packages retain their own licenses and terms.
