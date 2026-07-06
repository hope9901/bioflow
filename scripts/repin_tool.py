#!/usr/bin/env python3
"""Re-point a registry tool to a new image + digest, keeping recipes in lockstep.

The registry image and every ``@stage(image=...)`` in a recipe that pins the
tool must stay identical (the alignment guard enforces this).  This updates all
of them at once, so promoting a tool to a new build is one command instead of a
hand-edit spree.

    python scripts/repin_tool.py <tool_id> <new_image> <new_digest> [version]

``new_image`` is the tag form (e.g. ``ghcr.io/owner/bioflow-scanpy:1.12.2`` or
``quay.io/biocontainers/salmon:2.3.1--hfa8f182_0``); ``new_digest`` is the
``sha256:...`` the registry pins.
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "registry" / "tools"
RECIPES = ROOT / "bioflow" / "recipes"


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    tool_id, new_image, new_digest = sys.argv[1], sys.argv[2], sys.argv[3]
    version = sys.argv[4] if len(sys.argv) > 4 else None
    if not new_digest.startswith("sha256:"):
        print(f"digest must start with sha256: (got {new_digest!r})")
        return 2

    yaml_path = next(
        (p for p in sorted(TOOLS.rglob("*.yaml"))
         if re.search(rf"^id:\s*{re.escape(tool_id)}\s*$",
                      p.read_text(encoding="utf-8"), re.M)),
        None,
    )
    if yaml_path is None:
        print(f"tool id {tool_id!r} not found under {TOOLS}")
        return 1

    text = yaml_path.read_text(encoding="utf-8")
    m = re.search(r"^\s*image:\s*(\S+)", text, re.M)
    if not m:
        print(f"{yaml_path} has no image: line")
        return 1
    old_image = m.group(1)

    text = re.sub(r"(^\s*image:\s*)\S+", r"\g<1>" + new_image, text, count=1, flags=re.M)
    text = re.sub(r"(^\s*image_digest:\s*)\S+", r"\g<1>" + new_digest, text, count=1, flags=re.M)
    if version:
        text = re.sub(r'(^version:\s*)"?[^"\n]*"?', rf'\g<1>"{version}"', text, count=1, flags=re.M)
    today = _dt.date.today().isoformat()
    text = re.sub(r'(^last_reviewed:\s*)"?[^"\n]*"?', rf'\g<1>"{today}"', text, count=1, flags=re.M)
    yaml_path.write_text(text, encoding="utf-8")
    print(f"registry: {tool_id} -> {new_image}  ({new_digest})")

    n = 0
    for p in RECIPES.rglob("*.py"):
        s = p.read_text(encoding="utf-8")
        if old_image and old_image in s:
            p.write_text(s.replace(old_image, new_image), encoding="utf-8")
            print(f"  recipe: {p.relative_to(RECIPES)}")
            n += 1
    print(f"repinned {tool_id}: {old_image} -> {new_image}; {n} recipe file(s) updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
