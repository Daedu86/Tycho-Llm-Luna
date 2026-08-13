"""Runtime-selecting entry point for Nodes Tycho experiments."""
from __future__ import annotations

import os
from typing import Sequence

from . import harness, nodes_run
from .kubernetes_sandbox import KubernetesPodSandbox


def _configure_runtime() -> None:
    requested = os.environ.get("TYCHO_SANDBOX_RUNTIME", "auto").strip().lower()
    if requested != "kubernetes":
        return

    # Keep Docker/Finch as the default everywhere else. Only a Kubernetes Job
    # that explicitly requests the pod-isolation runtime swaps the harness and
    # doctor constructor for the pod-backed implementation.
    harness.PythonSandbox = KubernetesPodSandbox
    nodes_run.PythonSandbox = KubernetesPodSandbox


def main(argv: Sequence[str] | None = None) -> int:
    _configure_runtime()
    return nodes_run.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
