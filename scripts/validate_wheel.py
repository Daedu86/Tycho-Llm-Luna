#!/usr/bin/env python3
"""Check that a built wheel contains the complete Tycho runtime."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


REQUIRED = {
    "tycho/prompts/actor.system.j2",
    "tycho/prompts/partials/wm_single.j2",
    "tycho/workspace/templates/seed_world_model.py.tmpl",
    "tycho/workspace/templates/wm_feedback_probe.py.tmpl",
    "tycho/workspace/container/Containerfile",
    "tycho/workspace/sandbox.py",
    "tycho/viewer/serve.py",
    "tycho/viewer/viz.py",
}
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel
    if wheel.is_dir():
        candidates = list(wheel.glob("arc_agi_3_tycho-*.whl"))
        if not candidates:
            raise SystemExit(f"no Tycho wheel found in {wheel}")
        wheel = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_point_files = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        entry_points = "\n".join(archive.read(name).decode() for name in entry_point_files)
    missing = sorted(REQUIRED - names)
    missing_entry_points = []
    if "tycho-viewer = tycho.viewer.serve:main" not in entry_points:
        missing_entry_points.append("tycho-viewer")
    if "tycho-sandbox = tycho.workspace.sandbox:main" not in entry_points:
        missing_entry_points.append("tycho-sandbox")
    if missing or missing_entry_points:
        for name in missing:
            print(f"missing wheel resource: {name}")
        for name in missing_entry_points:
            print(f"missing wheel entry point: {name}")
        return 1
    print(f"WHEEL VALIDATION PASSED: {wheel.name} ({len(names)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
