#!/usr/bin/env python3
"""Regenerate Tycho's public release manifest from the tracked checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PUBLIC_RELEASE_MANIFEST.json"
DEFAULT_EXCLUDES = {
    "PUBLIC_RELEASE_MANIFEST.json",
    # M2 uses this workflow only as a temporary validation harness and removes it
    # after the branch is green. Do not make the release manifest depend on it.
    ".github/workflows/m2-kubernetes-validation.yml",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked_files() -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sorted(rel for rel in output.splitlines() if rel and rel not in DEFAULT_EXCLUDES)


def build_manifest() -> dict:
    existing = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    files = {rel: {"sha256": sha256(ROOT / rel)} for rel in tracked_files()}
    schema = existing.get("schema", "tycho.release_manifest")
    schema_version = existing.get("schema_version", 1)
    unchanged = (
        existing.get("schema") == schema
        and existing.get("schema_version") == schema_version
        and existing.get("files") == files
    )
    # Preserve generated_at for an already-current manifest so repeated CI runs
    # are byte-for-byte idempotent and cannot create a self-triggering commit loop.
    generated_at = (
        existing.get("generated_at")
        if unchanged and existing.get("generated_at")
        else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    return {
        "schema": schema,
        "schema_version": schema_version,
        "generated_at": generated_at,
        "files": files,
    }


def render(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if the committed manifest is stale.")
    args = parser.parse_args()

    generated = build_manifest()
    if args.check:
        if not MANIFEST.is_file():
            print("PUBLIC_RELEASE_MANIFEST.json is missing")
            return 1
        current = json.loads(MANIFEST.read_text(encoding="utf-8"))
        comparable_current = {key: current.get(key) for key in ("schema", "schema_version", "files")}
        comparable_generated = {key: generated.get(key) for key in ("schema", "schema_version", "files")}
        if comparable_current != comparable_generated:
            print("PUBLIC_RELEASE_MANIFEST.json is stale")
            return 1
        print("PUBLIC_RELEASE_MANIFEST.json is current")
        return 0

    MANIFEST.write_text(render(generated), encoding="utf-8")
    print(f"wrote {MANIFEST.relative_to(ROOT)} with {len(generated['files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
