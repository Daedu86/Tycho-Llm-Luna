# Codex + GPT-5.6 Luna transport

This fork includes an experimental Tycho transport that invokes GPT-5.6 Luna through the local
Codex CLI. Authentication stays with Codex; the plugin does not read or copy ChatGPT credentials.

## 1. Install and authenticate Codex

Install Codex using the official package for your platform, then authenticate locally:

```bash
codex login
codex login status
codex --version
```

Do not commit or share Codex authentication files.

## 2. Check out the transport branch

```bash
git checkout luna-codex-transport
git pull
```

Tycho requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## 3. Configure Tycho for Codex

Git Bash / Linux / macOS:

```bash
export TYCHO_LLM_PLUGIN=tycho.serving.codex_luna_plugin
export LLM_BACKEND=codex
export LLM_MODEL=gpt-5.6-luna
```

PowerShell:

```powershell
$env:TYCHO_LLM_PLUGIN = "tycho.serving.codex_luna_plugin"
$env:LLM_BACKEND = "codex"
$env:LLM_MODEL = "gpt-5.6-luna"
```

## 4. Zero-call preflight

This verifies the Codex executable, login status, required `codex exec` flags, and Tycho plugin
configuration without sending a model request:

```bash
python scripts/codex_preflight.py
```

Expected result begins with:

```text
CODEX PREFLIGHT PASSED:
```

## 5. Multimodal transport smoke

This sends exactly one Tycho model request containing text, a generated PNG, and one Tycho tool
schema. Passing means the Codex transport returned the expected `report_transport_ok` tool call.

```bash
python scripts/smoke_provider.py --confirm-external-call --effort low
```

Expected result:

```text
PROVIDER SMOKE PASSED: backend=codex model=gpt-5.6-luna ...
```

## 6. Bounded ARC baseline

After the provider smoke passes, configure `ARC_API_KEY` and run the existing bounded `tr87`
smoke. `configs/smoke/minimal.yaml` limits the run to two model calls and two tool steps.

```bash
TYCHO_MAX_LLM_CALLS=2 TYCHO_MAX_TOOL_STEPS=2 \
TYCHO_MAX_INFERENCE_COST_PER_GAME=0.50 TYCHO_ANIMATION_SUMMARY=0 \
python -m tycho.harness.run_parallel \
  --approach tycho --games tr87 --out-dir results/luna-smoke \
  --config configs/smoke/minimal.yaml --max-workers 1
```

Keep the Codex transport environment variables from step 3 active for this run.

## 7. Validation order

Use this order so failures are attributable and model quota is not wasted:

1. `python scripts/codex_preflight.py`
2. `python -m pytest tests/serving/test_codex_luna_plugin.py -q`
3. `python scripts/smoke_provider.py --confirm-external-call --effort low`
4. bounded `tr87`
5. only then begin neuro-symbolic changes and A/B evaluation

The first baseline should preserve Tycho's existing policy so any later gain can be attributed to
the neuro-symbolic architecture rather than to simultaneous transport and policy changes.
