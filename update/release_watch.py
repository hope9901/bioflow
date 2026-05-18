"""Weekly GitHub release watcher (T2 cadence).

For every tool YAML in ``registry/tools/`` that declares a
``source_repo: <owner>/<repo>`` field, query the GitHub releases API
for the latest tag.  When the tag is newer than the YAML's pinned
``version``, write a candidate YAML draft into
``update/candidates/<YYYY-MM>/`` so the existing monthly cron picks
it up at the next benchmark window.

State is tracked in ``update/release_watch_state.json`` so we never
file the same candidate twice.

The candidate is a near-copy of the original tool YAML with:
  * ``version:`` bumped to the GitHub release tag
  * ``container.image:`` tag suffix updated *best-effort*
    (BioContainers builds usually lag GitHub by a few days — a
    ``# TODO`` comment instructs the maintainer to confirm before
    benchmarking)
  * ``last_reviewed:`` set to today
  * ``update_meta.source: release_watch``

This script is read-only against the registry and the network; it
only writes to ``update/candidates/`` and ``update/release_watch_state.json``.

Network: stdlib only.  GitHub API rate limits unauthenticated callers
to 60 requests/hour; set the env var ``GITHUB_TOKEN`` to raise this to
5000/hour.

Usage::

    python -m update.release_watch                     # default paths
    python -m update.release_watch --dry-run           # report only
    python -m update.release_watch --token <PAT>       # explicit token
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "registry" / "tools"
DEFAULT_CANDIDATES_DIR = REPO_ROOT / "update" / "candidates"
DEFAULT_STATE = REPO_ROOT / "update" / "release_watch_state.json"


# ---------------------------------------------------------------------------
# GitHub releases API
# ---------------------------------------------------------------------------

def _http_json(url: str, token: Optional[str] = None,
               timeout: float = 15.0) -> dict:
    headers = {
        "User-Agent": "bioflow-release-watch/0.1",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_release_tag(source_repo: str, token: Optional[str] = None) -> Optional[str]:
    """Return GitHub's "latest" release tag, or None on 404 (no releases)."""
    url = f"https://api.github.com/repos/{source_repo}/releases/latest"
    try:
        data = _http_json(url, token=token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    tag = data.get("tag_name", "")
    # GitHub tags often have a leading "v" — strip for comparison
    return tag.lstrip("v") if tag else None


# ---------------------------------------------------------------------------
# Version comparison (reuse semantics from freshness_check)
# ---------------------------------------------------------------------------

_PART_RE = re.compile(r"(\d+)|([a-zA-Z]+)")


def _version_key(s: str) -> tuple:
    parts = []
    for num, alpha in _PART_RE.findall(s):
        if num:
            parts.append((0, int(num)))
        else:
            parts.append((1, alpha.lower()))
    return tuple(parts)


def is_newer(a: str, b: str) -> bool:
    """True iff a sorts strictly higher than b."""
    try:
        return _version_key(a) > _version_key(b)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _bump_image_tag(image: str, new_version: str) -> str:
    """Best-effort tag rewrite.  For images like ``foo/bar:1.2.3`` we
    swap the tag; for BioContainers-style tags with build suffix
    (``--h12345_0``) we drop the suffix and leave a placeholder."""
    if ":" not in image:
        return image
    base, _ = image.rsplit(":", 1)
    return f"{base}:{new_version}"


def make_candidate(tool_doc: dict, new_version: str, today: str) -> dict:
    doc = dict(tool_doc)   # shallow copy is fine — we replace top-level keys
    doc["version"] = new_version
    container = dict(doc.get("container", {}))
    container["image"] = _bump_image_tag(container.get("image", ""), new_version)
    doc["container"] = container
    doc["last_reviewed"] = today
    doc["update_meta"] = {
        "month": today[:7],
        "source": "release_watch",
        "previous_version": tool_doc.get("version"),
        "previous_image": tool_doc.get("container", {}).get("image"),
        "note": (
            "Auto-filed by update/release_watch.py. "
            "Confirm the BioContainers tag exists before benchmark; "
            "the bumped tag is a best-effort guess."
        ),
        "risks": ["unverified image tag"],
    }
    return doc


# ---------------------------------------------------------------------------
# State (don't re-file the same candidate)
# ---------------------------------------------------------------------------

def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True),
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def scan(
    registry_dir: Path,
    candidates_dir: Path,
    state_path: Path,
    token: Optional[str] = None,
    dry_run: bool = False,
) -> list[dict]:
    """Scan registry; file candidates for any tool whose upstream has a
    newer GitHub release than the YAML's pinned version."""
    state = load_state(state_path)
    today = dt.date.today().isoformat()
    month_dir = candidates_dir / today[:7]
    actions: list[dict] = []

    for tool_yaml in sorted(registry_dir.rglob("*.yaml")):
        doc = yaml.safe_load(tool_yaml.read_text(encoding="utf-8"))
        src = doc.get("source_repo")
        if not src:
            continue
        tool_id = doc.get("id")
        current_version = str(doc.get("version", ""))

        try:
            upstream = latest_release_tag(src, token=token)
        except urllib.error.HTTPError as e:
            actions.append({
                "tool": tool_id, "result": "http_error",
                "detail": f"HTTP {e.code} from GitHub for {src}",
            })
            continue
        except Exception as e:
            actions.append({
                "tool": tool_id, "result": "error",
                "detail": f"{type(e).__name__}: {e}",
            })
            continue

        if upstream is None:
            actions.append({
                "tool": tool_id, "result": "no_releases",
                "detail": f"{src} has no GitHub releases",
            })
            continue

        if not is_newer(upstream, current_version):
            actions.append({
                "tool": tool_id, "result": "up_to_date",
                "detail": f"upstream {upstream} ≤ pinned {current_version}",
            })
            continue

        # Newer release — have we already filed this one?
        already = state.get(tool_id, {}).get("last_filed_version")
        if already == upstream:
            actions.append({
                "tool": tool_id, "result": "already_filed",
                "detail": f"candidate for {upstream} already exists",
            })
            continue

        if dry_run:
            actions.append({
                "tool": tool_id, "result": "would_file",
                "detail": f"{current_version} → {upstream}",
            })
            continue

        # File the candidate
        month_dir.mkdir(parents=True, exist_ok=True)
        candidate = make_candidate(doc, upstream, today)
        out_path = month_dir / f"{tool_id}.yaml"
        out_path.write_text(
            yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8",
        )
        try:
            rel = out_path.relative_to(REPO_ROOT)
        except ValueError:
            rel = out_path
        state[tool_id] = {
            "last_filed_version": upstream,
            "filed_at": today,
            "out_path": str(rel),
        }
        actions.append({
            "tool": tool_id, "result": "filed",
            "detail": f"{current_version} → {upstream}  ({out_path.name})",
        })

    if not dry_run:
        save_state(state_path, state)
    return actions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="release_watch",
        description="Weekly GitHub release watcher.",
    )
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--candidates-dir", type=Path, default=DEFAULT_CANDIDATES_DIR)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--token", type=str, default=os.environ.get("GITHUB_TOKEN"),
                    help="GitHub PAT (env GITHUB_TOKEN as default).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report only; do not write candidate files or state.")
    args = ap.parse_args(argv)

    actions = scan(
        args.registry, args.candidates_dir, args.state,
        token=args.token, dry_run=args.dry_run,
    )
    by_result: dict[str, int] = {}
    for a in actions:
        by_result[a["result"]] = by_result.get(a["result"], 0) + 1
        print(f"  [{a['result']:14s}] {a['tool']:20s} {a['detail']}")
    print(f"\nSummary: {sum(by_result.values())} tools checked")
    for r, n in sorted(by_result.items()):
        print(f"  {r:14s} {n}")

    # Exit non-zero if any candidate was filed (CI can pick this up)
    return 1 if by_result.get("filed", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
