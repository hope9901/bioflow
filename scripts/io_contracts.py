#!/usr/bin/env python3
"""Track each tool's input/output *format contract* across version bumps.

Every registry entry declares the data formats a tool consumes
(``input_types``) and produces (``output_types``).  Recipes chain tools, so a
version bump that silently changes a tool's I/O contract can break a downstream
stage that fed on the old shape of its output.

This keeps a committed snapshot of every tool's ``(version, inputs, outputs)``
in ``registry/io_contracts.json`` and turns a bump into a reviewable event:

* ``check`` — compare the live YAMLs to the snapshot.  If a tool's **version**
  changed *and* its I/O contract changed, that's **contract drift**: the report
  names the recipes that use the tool so the bump author re-verifies them
  before shipping.  Any difference at all (drift *or* a plain refresh) fails
  until the snapshot is regenerated, so it can never silently go stale — the
  same gate style as docs-fresh.
* ``update`` — regenerate the snapshot once the affected recipes are verified.

    python scripts/io_contracts.py check
    python scripts/io_contracts.py update

The point is not to *auto-migrate* pipelines (formats are semantic, not
mechanically convertible) but to make every I/O-changing bump loud and to point
straight at the pipelines that need a human's eyes — so recipes and
user-defined pipelines keep working across upgrades.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "registry" / "tools"
RECIPES = ROOT / "bioflow" / "recipes"
SNAPSHOT = ROOT / "registry" / "io_contracts.json"


def _load_live() -> dict[str, dict]:
    """{tool_id: {version, image, inputs, outputs}} from the registry YAMLs."""
    live: dict[str, dict] = {}
    for p in sorted(TOOLS.rglob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not d or "id" not in d:
            continue
        live[d["id"]] = {
            "version": str(d.get("version", "")),
            "image": (d.get("container") or {}).get("image", ""),
            "inputs": sorted(d.get("input_types") or []),
            "outputs": sorted(d.get("output_types") or []),
        }
    return live


def _tool_recipes(live: dict[str, dict]) -> dict[str, list[str]]:
    """{tool_id: [recipe file, ...]} — recipes whose @stage pins the tool image."""
    # image string -> recipe files that reference it
    img_refs: dict[str, list[str]] = {}
    pat = re.compile(r'image\s*=\s*["\']([^"\']+)["\']')
    for p in RECIPES.rglob("*.py"):
        for m in pat.finditer(p.read_text(encoding="utf-8")):
            img_refs.setdefault(m.group(1), []).append(
                str(p.relative_to(ROOT)).replace("\\", "/")
            )
    out: dict[str, list[str]] = {}
    for tid, info in live.items():
        refs = img_refs.get(info["image"], [])
        if refs:
            out[tid] = sorted(set(refs))
    return out


def _load_snapshot() -> dict[str, dict]:
    if not SNAPSHOT.exists():
        return {}
    return json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("tools", {})


def _write_snapshot(live: dict[str, dict]) -> None:
    # Drop the volatile image tag from the snapshot — the contract is about
    # version + formats, not the build-suffixed image string.
    tools = {
        tid: {"version": v["version"], "inputs": v["inputs"], "outputs": v["outputs"]}
        for tid, v in sorted(live.items())
    }
    payload = {
        "_comment": "I/O format contract snapshot — regenerate with "
        "`python scripts/io_contracts.py update`.  See scripts/io_contracts.py.",
        "generated": _dt.date.today().isoformat(),
        "tools": tools,
    }
    SNAPSHOT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _diff(live: dict[str, dict], snap: dict[str, dict]):
    """Return (added, removed, io_drift, version_only, refresh_only)."""
    added = sorted(set(live) - set(snap))
    removed = sorted(set(snap) - set(live))
    io_drift, version_only, refresh = [], [], []
    for tid in sorted(set(live) & set(snap)):
        lv, sv = live[tid], snap[tid]
        ver_changed = lv["version"] != sv.get("version")
        io_changed = (
            lv["inputs"] != sv.get("inputs", [])
            or lv["outputs"] != sv.get("outputs", [])
        )
        if ver_changed and io_changed:
            io_drift.append(tid)
        elif ver_changed:
            version_only.append(tid)
        elif io_changed:
            refresh.append(tid)
    return added, removed, io_drift, version_only, refresh


def _fmt_io(old: dict, new: dict, key: str) -> str:
    o, n = old.get(key, []), new.get(key, [])
    gained = [x for x in n if x not in o]
    lost = [x for x in o if x not in n]
    bits = []
    if lost:
        bits.append("-" + ",".join(lost))
    if gained:
        bits.append("+" + ",".join(gained))
    return f"{key}: {' '.join(bits)}" if bits else ""


def check() -> int:
    live = _load_live()
    snap = _load_snapshot()
    added, removed, io_drift, version_only, refresh = _diff(live, snap)
    recipes = _tool_recipes(live)

    if not (added or removed or io_drift or version_only or refresh):
        print(f"OK: I/O contracts match the snapshot ({len(live)} tools).")
        return 0

    if io_drift:
        print("::warning::I/O contract drift on a version bump - verify the "
              "recipes below still work, then run "
              "`python scripts/io_contracts.py update`.\n")
        for tid in io_drift:
            lv, sv = live[tid], snap[tid]
            print(f"  {tid}: {sv.get('version')} -> {lv['version']}")
            for key in ("inputs", "outputs"):
                line = _fmt_io(sv, lv, key)
                if line:
                    print(f"      {line}")
            affected = recipes.get(tid)
            if affected:
                print(f"      affected recipes: {', '.join(affected)}")
            else:
                print("      affected recipes: none (catalog-only tool)")
        print()

    for label, ids in (("added", added), ("removed", removed),
                       ("version-only (I/O unchanged)", version_only),
                       ("I/O changed without a version bump", refresh)):
        if ids:
            print(f"  {label}: {', '.join(ids)}")

    print("\n::error::io_contracts snapshot is stale - after verifying any "
          "drift above, run `python scripts/io_contracts.py update` and commit "
          "registry/io_contracts.json.")
    return 1


def update() -> int:
    live = _load_live()
    _write_snapshot(live)
    print(f"wrote {SNAPSHOT.relative_to(ROOT)} ({len(live)} tools).")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    if cmd == "check":
        return check()
    if cmd == "update":
        return update()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
