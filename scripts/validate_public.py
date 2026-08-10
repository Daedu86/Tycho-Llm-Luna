#!/usr/bin/env python3
"""Credential-free validation of a Tycho checkout."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PUBLIC_RELEASE_MANIFEST.json"
TEXT_SUFFIXES = {".cff", ".csv", ".example", ".j2", ".json", ".md", ".py", ".tmpl", ".toml", ".txt", ".yaml", ".yml"}
TEXT_FILENAMES = {".gitignore", "Containerfile", "LICENSE", "Makefile"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    re.compile(r"/(?:Users|home)/[^/\s\"']+/"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+\\"),
)


def _sha(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_FILENAMES:
        # Git can materialize text with CRLF on Windows. The release manifest
        # records canonical LF content, so normalize line endings only for
        # known text files while keeping binary files byte-exact.
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _manifest_checks() -> list[str]:
    errors = []
    if not MANIFEST.is_file():
        return ["PUBLIC_RELEASE_MANIFEST.json is missing"]
    manifest = json.loads(MANIFEST.read_text())
    if manifest.get("schema") != "tycho.release_manifest":
        errors.append("unexpected release-manifest schema")
    allowed_top_level = {"schema", "schema_version", "generated_at", "files"}
    unexpected = set(manifest) - allowed_top_level
    if unexpected:
        errors.append(f"unexpected release-manifest fields: {sorted(unexpected)}")
    expected = manifest.get("files") or {}
    for rel, metadata in expected.items():
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"manifest file is missing: {rel}")
        elif set(metadata) != {"sha256"}:
            errors.append(f"unexpected manifest metadata for {rel}: {sorted(metadata)}")
        elif _sha(path) != metadata.get("sha256"):
            errors.append(f"manifest hash mismatch: {rel}")
    try:
        tracked = set(
            subprocess.run(
                ["git", "-C", str(ROOT), "ls-files"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
    except (OSError, subprocess.CalledProcessError):
        tracked = set()
    if tracked:
        declared = set(expected) | {MANIFEST.name}
        for rel in sorted(tracked - declared):
            errors.append(f"tracked file is absent from release manifest: {rel}")
    return errors


def _content_checks() -> list[str]:
    errors = []
    manifest = json.loads(MANIFEST.read_text())
    paths = [ROOT / rel for rel in manifest.get("files", {})] + [MANIFEST]
    for path in paths:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"possible credential or local path: {path.relative_to(ROOT)}")
    return errors


def _config_checks() -> list[str]:
    from tycho.config.run_config import CONFIG_KEYS, apply_config_file, resolve_orchestration
    from tycho.config.settings import TychoSettings
    from tycho.serving import llm_client

    errors = []
    original = dict(os.environ)
    original_extension = llm_client._extension
    try:
        llm_client._extension = lambda: None
        for path in sorted((ROOT / "configs" / "paper").glob("*.yaml")):
            os.environ.clear()
            os.environ.update(original)
            for key in CONFIG_KEYS:
                os.environ.pop(key.env, None)
            for name in ("LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
                os.environ.pop(name, None)
            apply_config_file(path)
            backend = os.environ.get("LLM_BACKEND")
            if backend == "anthropic":
                os.environ["ANTHROPIC_API_KEY"] = "offline-validation"
            elif backend == "openai_responses":
                os.environ["OPENAI_API_KEY"] = "offline-validation"
            try:
                llm = llm_client.LLMConfig.from_env()
                settings = TychoSettings.from_env()
                orchestration = resolve_orchestration(path) or {}
                if settings.mode != orchestration.get("mode"):
                    errors.append(f"mode mismatch in {path.relative_to(ROOT)}")
                if llm.model != os.environ.get("LLM_MODEL"):
                    errors.append(f"model mismatch in {path.relative_to(ROOT)}")
            except (Exception, SystemExit) as exc:  # noqa: BLE001 - aggregate release errors
                errors.append(f"invalid config {path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
        smoke = ROOT / "configs" / "smoke" / "minimal.yaml"
        os.environ.clear()
        os.environ.update(original)
        for key in CONFIG_KEYS:
            os.environ.pop(key.env, None)
        os.environ.update(
            LLM_BACKEND="anthropic",
            LLM_MODEL="offline-model",
            ANTHROPIC_API_KEY="offline-validation",
        )
        try:
            apply_config_file(smoke)
            settings = TychoSettings.from_env()
            if settings.mode != "no_world_model" or settings.max_calls != 2:
                errors.append("bounded smoke config lost its mode or two-call ceiling")
        except (Exception, SystemExit) as exc:  # noqa: BLE001 - aggregate release errors
            errors.append(f"invalid config {smoke.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
    finally:
        llm_client._extension = original_extension
        os.environ.clear()
        os.environ.update(original)
    return errors


def _artifact_checks() -> list[str]:
    errors = []
    scorecards = sorted((ROOT / "artifacts" / "scorecards").glob("*.json"))
    if len(scorecards) != 6:
        errors.append(f"expected 6 scorecard artifacts, found {len(scorecards)}")
    for path in scorecards:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid scorecard {path.relative_to(ROOT)}: {exc}")
            continue
        card_id = data.get("scorecard_id")
        if data.get("schema") != "tycho.public_scorecard_evidence":
            errors.append(f"unexpected scorecard schema: {path.relative_to(ROOT)}")
        if data.get("operation_mode") != "competition":
            errors.append(f"scorecard is not competition-mode: {path.relative_to(ROOT)}")
        if len(data.get("completed_games") or []) != 25 or len(data.get("environments") or []) != 25:
            errors.append(f"scorecard does not cover 25 games: {path.relative_to(ROOT)}")
        if not card_id or not str(data.get("scorecard_url", "")).endswith(str(card_id)):
            errors.append(f"scorecard URL/ID mismatch: {path.relative_to(ROOT)}")

    metrics_path = ROOT / "artifacts" / "appendix_metrics.json"
    integrity_path = ROOT / "artifacts" / "evaluation_integrity.json"
    try:
        metrics = json.loads(metrics_path.read_text())
        if any("git_version" in run for run in metrics.values()):
            errors.append("appendix metrics must not include source revisions")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid appendix metrics: {exc}")
    try:
        integrity = json.loads(integrity_path.read_text())
        selected = integrity.get("selected_policy_runs") or {}
        if set(selected) != {"GPT-5.6 Sol", "Opus 5"}:
            errors.append("evaluation integrity does not describe both selected-policy runs")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid evaluation integrity: {exc}")
    return errors


def _cli_checks() -> list[str]:
    errors = []
    for module in (
        "tycho.harness.run_parallel",
        "tycho.harness.submission_replay",
        "tycho.harness.planner_follow_diagnostics",
        "tycho.viewer.serve",
    ):
        result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            errors.append(f"CLI failed: {module}: {result.stderr.strip()}")
    return errors


def main() -> int:
    errors = _manifest_checks()
    if MANIFEST.is_file():
        errors.extend(_content_checks())
    errors.extend(_config_checks())
    errors.extend(_artifact_checks())
    errors.extend(_cli_checks())
    if errors:
        print("TYCHO VALIDATION FAILED")
        for error in errors:
            print(f"  - {error}")
        return 1
    count = len(json.loads(MANIFEST.read_text()).get("files") or {})
    config_count = len(list((ROOT / "configs" / "paper").glob("*.yaml"))) + 1
    print(
        f"TYCHO VALIDATION PASSED: {count} manifest files, "
        f"{config_count} configs, no credentials used"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
