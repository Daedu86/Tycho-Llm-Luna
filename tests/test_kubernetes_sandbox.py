from __future__ import annotations

from pathlib import Path

import pytest

from tycho.experiments.kubernetes_sandbox import KubernetesPodSandbox
from tycho.workspace.sandbox import SandboxError


def isolated_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "TYCHO_KUBERNETES_ISOLATED": "1",
        "TYCHO_KUBERNETES_NETWORK_POLICY": "deny-all",
        "TYCHO_KUBERNETES_SERVICE_ACCOUNT_TOKEN": "disabled",
        "TYCHO_KUBERNETES_IMAGE": "tycho:test",
    }


def test_kubernetes_sandbox_fails_closed_without_isolation_attestation() -> None:
    sandbox = KubernetesPodSandbox(environment={"PATH": "/usr/bin:/bin"})
    with pytest.raises(SandboxError, match="isolation attestation failed"):
        sandbox.check(require_isolation=True)


def test_kubernetes_sandbox_executes_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "verify.py"
    script.write_text(
        "from pathlib import Path\n"
        "Path('metric.txt').write_text('ok')\n"
        "print('pass')\n",
        encoding="utf-8",
    )

    sandbox = KubernetesPodSandbox(environment=isolated_env())
    readiness = sandbox.check(require_isolation=True)
    result = sandbox.run_script(workspace, script, timeout=5)

    assert readiness["runtime"] == "kubernetes"
    assert readiness["isolationBoundary"] == "kubernetes-pod"
    assert result.returncode == 0
    assert result.timed_out is False
    assert result.stdout.strip() == "pass"
    assert (workspace / "metric.txt").read_text(encoding="utf-8") == "ok"


def test_kubernetes_sandbox_does_not_forward_runner_credentials(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "env.py"
    script.write_text(
        "import os\nprint(os.environ.get('CODEX_RUNNER_TOKEN', 'absent'))\n",
        encoding="utf-8",
    )
    environment = isolated_env() | {"CODEX_RUNNER_TOKEN": "must-not-leak"}

    result = KubernetesPodSandbox(environment=environment).run_script(
        workspace, script, timeout=5
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "absent"
