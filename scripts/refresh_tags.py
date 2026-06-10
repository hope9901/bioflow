"""Repair stale BioContainer image tags in the registry.

BioContainers republishes each package version under rotating build
suffixes (``<version>--<buildhash>_<buildnum>``).  Quay garbage-collects
the older build tags, so a registry entry pinned to
``salmon:1.10.3--hb950928_0`` silently 404s months later even though
``salmon:1.10.3`` still exists under a newer build hash.  Every recipe
that pulls such an image then fails at run time with a "not found"
error that has nothing to do with the user's data.

This script audits every ``quay.io/biocontainers/<pkg>:<ver>--<build>``
reference in ``registry/tools/**`` and, when the exact tag no longer
exists, finds the newest *same-version* build tag still active on Quay
and (with ``--apply``) rewrites the YAML to point at it.  It never
changes the upstream **version** — only the rotting build suffix — so
recipe behaviour is unchanged.

Non-Quay images (staphb/*, dockerhub user images such as
``satijalab/seurat``) are reported for manual review but not touched.

Usage
-----
::

    python scripts/refresh_tags.py             # audit only (report)
    python scripts/refresh_tags.py --apply     # rewrite stale tags in place
    python scripts/refresh_tags.py --apply foo bar   # limit to tool stems

After ``--apply`` run ``python scripts/pin_digests.py`` to pin the new
tags' digests.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

# Windows cp949 consoles choke on the em-dash / arrow glyphs we print.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass

REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "tools"
QUAY_BIOCONTAINERS = "quay.io/biocontainers/"
_IMAGE_LINE = re.compile(r"^(\s*image:\s*)(\S+)\s*$")


def _quay_tag_exists(pkg: str, tag: str) -> bool:
    url = (
        f"https://quay.io/api/v1/repository/biocontainers/{pkg}"
        f"/tag/?specificTag={tag}&onlyActiveTags=true"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            doc = json.load(r)
    except Exception:
        return False
    return bool(doc.get("tags"))


def _quay_latest_same_version(pkg: str, version: str) -> str | None:
    """Return the newest active ``<version>--<build>`` tag, or None."""
    url = (
        f"https://quay.io/api/v1/repository/biocontainers/{pkg}"
        f"/tag/?limit=100&onlyActiveTags=true"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            doc = json.load(r)
    except Exception:
        return None
    prefix = f"{version}--"
    same = [
        t for t in doc.get("tags", [])
        if t.get("name", "").startswith(prefix)
    ]
    if not same:
        return None
    same.sort(key=lambda t: t.get("start_ts", 0), reverse=True)
    return same[0]["name"]


def _parse_quay_ref(image: str) -> tuple[str, str, str] | None:
    """``quay.io/biocontainers/salmon:1.10.3--hb950928_0`` →
    ``(pkg, version, full_tag)``.  Returns None for non-Quay images or
    tags without the ``--build`` suffix."""
    if not image.startswith(QUAY_BIOCONTAINERS):
        return None
    rest = image[len(QUAY_BIOCONTAINERS):]
    if ":" not in rest:
        return None
    pkg, tag = rest.split(":", 1)
    if "--" not in tag:
        return None
    version = tag.split("--", 1)[0]
    return pkg, version, tag


def audit_one(path: Path, apply: bool) -> tuple[str, str]:
    """Return (status, message).  status ∈ {ok, fixed, version_gone, stale_fix, manual, skip}."""
    text = path.read_text(encoding="utf-8")
    m = None
    for line in text.splitlines():
        lm = _IMAGE_LINE.match(line)
        if lm:
            m = lm
            break
    if not m:
        return ("skip", "no image line")
    image = m.group(2)

    parsed = _parse_quay_ref(image)
    if parsed is None:
        # Non-Quay (staphb, dockerhub) — report for manual review only.
        return ("manual", image)

    pkg, version, tag = parsed
    if _quay_tag_exists(pkg, tag):
        return ("ok", tag)

    # Stale — find newest same-version build.
    new_tag = _quay_latest_same_version(pkg, version)
    if new_tag is None:
        return ("version_gone", f"{pkg}:{tag} — no active {version}--* build on Quay")

    new_image = f"{QUAY_BIOCONTAINERS}{pkg}:{new_tag}"
    if not apply:
        return ("stale_fix", f"{tag} -> {new_tag}")

    # Rewrite the image line, dropping any now-wrong image_digest so
    # pin_digests.py re-resolves it.
    new_lines = []
    for line in text.splitlines():
        lm = _IMAGE_LINE.match(line)
        if lm and lm.group(2) == image:
            new_lines.append(f"{lm.group(1)}{new_image}")
        elif re.match(r"^\s*image_digest:\s*\S+", line):
            continue  # drop stale digest
        else:
            new_lines.append(line)
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return ("fixed", f"{tag} -> {new_tag}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("tools", nargs="*", help="Optional tool stems to limit the run.")
    p.add_argument("--apply", action="store_true",
                   help="Rewrite stale tags in place (default: report only).")
    args = p.parse_args(argv)

    paths = sorted(REGISTRY.rglob("*.yaml"))
    if args.tools:
        paths = [p for p in paths if p.stem in args.tools]

    counts: dict[str, int] = {}
    manual: list[str] = []
    gone: list[str] = []
    for path in paths:
        status, msg = audit_one(path, apply=args.apply)
        counts[status] = counts.get(status, 0) + 1
        if status == "manual":
            manual.append(f"{path.stem}: {msg}")
            continue
        if status == "version_gone":
            gone.append(f"{path.stem}: {msg}")
        tag = {
            "ok": "ok  ", "fixed": "FIX ", "stale_fix": "STALE",
            "version_gone": "GONE", "skip": "skip",
        }.get(status, status)
        if status not in ("ok", "manual", "skip"):
            print(f"  {tag}  {path.relative_to(REGISTRY.parent.parent)}  {msg}")

    print(
        f"\nSummary: ok={counts.get('ok',0)} "
        f"{'fixed' if args.apply else 'stale'}="
        f"{counts.get('fixed',0) + counts.get('stale_fix',0)} "
        f"version_gone={counts.get('version_gone',0)} "
        f"manual(non-quay)={counts.get('manual',0)} "
        f"skip={counts.get('skip',0)}"
    )
    if gone:
        print("\nVersion no longer on Quay (need a manual version bump):")
        for g in gone:
            print(f"  - {g}")
    if manual:
        print("\nNon-Quay images (review manually):")
        for mm in manual:
            print(f"  - {mm}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
