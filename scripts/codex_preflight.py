#!/usr/bin/env python3
"""Credential-safe, zero-model-call preflight for the Tycho Codex transport."""

from __future__ import annotations

import os
import shutil
import subprocess


REQUIRED_EXEC_FLAGS = {
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--skip-git-repo-check",
    "--cd",
    "--sandbox",
    "--image",
    "--model",
    "--output-schema",
    "--json",
}


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def main() -> int:
    binary_name = os.environ.get("CODEX_BINARY", "codex")
    binary = shutil.which(binary_name)
    if not binary:
        print(f"CODEX PREFLIGHT FAILED: executable {binary_name!r} was not found")
        return 1

    version = _run([binary, "--version"])
    if version.returncode:
        print("CODEX PREFLIGHT FAILED: `codex --version` failed")
        print((version.stderr or version.stdout).strip())
        return 1

    login = _run([binary, "login", "status"])
    if login.returncode:
        print("CODEX PREFLIGHT FAILED: no usable Codex login")
        print((login.stderr or login.stdout).strip())
        print("Run: codex login")
        return 1

    help_result = _run([binary, "exec", "--help"])
    if help_result.returncode:
        print("CODEX PREFLIGHT FAILED: `codex exec --help` failed")
        print((help_result.stderr or help_result.stdout).strip())
        return 1

    help_text = (help_result.stdout or "") + "\n" + (help_result.stderr or "")
    missing = sorted(flag for flag in REQUIRED_EXEC_FLAGS if flag not in help_text)
    if missing:
        print(f"CODEX PREFLIGHT FAILED: missing exec flags: {', '.join(missing)}")
        return 1

    os.environ.setdefault("TYCHO_LLM_PLUGIN", "tycho.serving.codex_luna_plugin")
    os.environ.setdefault("LLM_BACKEND", "codex")
    os.environ.setdefault("LLM_MODEL", "gpt-5.6-luna")

    try:
        from tycho.serving.llm_client import LLMConfig, public_identity

        cfg = LLMConfig.from_env()
        identity = public_identity(cfg)
    except SystemExit as exc:
        print(f"CODEX PREFLIGHT FAILED: Tycho config error: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - diagnostic boundary
        print(
            "CODEX PREFLIGHT FAILED: Tycho plugin import/config error: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1

    if cfg.backend != "codex" or cfg.model != os.environ["LLM_MODEL"]:
        print(
            "CODEX PREFLIGHT FAILED: unexpected resolved config "
            f"backend={cfg.backend!r} model={cfg.model!r}"
        )
        return 1

    print(
        "CODEX PREFLIGHT PASSED: "
        f"{version.stdout.strip() or version.stderr.strip()} | "
        f"{login.stdout.strip() or login.stderr.strip()} | "
        f"protocol={identity['api_protocol']} model={identity['model']} | "
        "no model request sent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
