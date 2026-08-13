"""Kubernetes-pod execution boundary for Tycho experiments.

The Kubernetes Job/Pod is the isolation boundary. This adapter intentionally
executes experiment scripts as child Python processes *inside* that pod instead
of nesting Docker/Finch or mounting a container runtime socket.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

from tycho.workspace.sandbox import SandboxError, SandboxResult


REQUIRED_MARKERS = {
    "TYCHO_KUBERNETES_ISOLATED": "1",
    "TYCHO_KUBERNETES_NETWORK_POLICY": "deny-all",
    "TYCHO_KUBERNETES_SERVICE_ACCOUNT_TOKEN": "disabled",
}


def _marker_errors(environment: Mapping[str, str]) -> list[str]:
    return [
        f"{name}={expected!r} is required"
        for name, expected in REQUIRED_MARKERS.items()
        if environment.get(name) != expected
    ]


class KubernetesPodSandbox:
    """Execute workspace-authored Python inside an already isolated Kubernetes pod."""

    runtime = "kubernetes"

    def __init__(self, *, environment: Mapping[str, str] | None = None):
        self._environment = dict(os.environ if environment is None else environment)
        self.image = self._environment.get("TYCHO_KUBERNETES_IMAGE", "kubernetes-pod")

    @staticmethod
    def _workspace(path: str | Path) -> Path:
        workspace = Path(path).resolve(strict=True)
        if not workspace.is_dir():
            raise SandboxError(f"workspace is not a directory: {workspace}")
        return workspace

    @staticmethod
    def _script(workspace: Path, path: str | Path) -> Path:
        script = Path(path).resolve(strict=True)
        try:
            script.relative_to(workspace)
        except ValueError as exc:
            raise SandboxError(f"script is outside workspace: {script}") from exc
        if not script.is_file():
            raise SandboxError(f"script is not a file: {script}")
        return script

    @staticmethod
    def _portable_output(value: str, workspace: Path) -> str:
        return (value or "").replace(str(workspace), "/workspace")

    def _child_environment(self) -> dict[str, str]:
        # Do not forward host/runner credentials into experiment steps. The pod
        # gets only the minimal deterministic Python process environment.
        path_value = self._environment.get("PATH", os.defpath)
        return {
            "PATH": path_value,
            "HOME": "/tmp",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }

    def check(self, *, require_isolation: bool = False) -> dict:
        errors = _marker_errors(self._environment)
        if require_isolation and errors:
            raise SandboxError(
                "Kubernetes pod isolation attestation failed: " + "; ".join(errors)
            )
        return {
            "runtime": self.runtime,
            "image": self.image,
            "isolationBoundary": "kubernetes-pod",
            "networkPolicy": self._environment.get("TYCHO_KUBERNETES_NETWORK_POLICY"),
            "serviceAccountToken": self._environment.get(
                "TYCHO_KUBERNETES_SERVICE_ACCOUNT_TOKEN"
            ),
        }

    def run_script(
        self,
        workspace: str | Path,
        script: str | Path,
        *,
        timeout: int | float,
        args: tuple[str, ...] = (),
    ) -> SandboxResult:
        ws = self._workspace(workspace)
        script_path = self._script(ws, script)
        try:
            completed = subprocess.run(
                [sys.executable, "-B", str(script_path), *args],
                cwd=ws,
                env=self._child_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                self._portable_output(exc.stdout or "", ws),
                self._portable_output(exc.stderr or "", ws),
                -1,
                timed_out=True,
            )
        except OSError as exc:
            raise SandboxError(f"unable to execute Kubernetes pod sandbox script: {exc}") from exc

        return SandboxResult(
            self._portable_output(completed.stdout, ws),
            self._portable_output(completed.stderr, ws),
            completed.returncode,
            timed_out=False,
        )


def create_experiment_sandbox():
    """Select the experiment sandbox without weakening local isolation defaults."""
    requested = os.environ.get("TYCHO_SANDBOX_RUNTIME", "auto").strip().lower()
    if requested == "kubernetes":
        return KubernetesPodSandbox()

    from tycho.workspace.sandbox import PythonSandbox

    return PythonSandbox(runtime=None if requested == "auto" else requested)
