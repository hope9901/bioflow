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
  * ``container.image:`` repointed at the **real** BioContainers build
    for that version — resolved from the quay.io tags API, matching the
    current image's Python build family (``py311`` etc.) when there are
    several.  If no build exists yet (or the image is self-built, not a
    BioContainer) the tag is a best-effort guess and ``update_meta.risks``
    says so.
  * ``container.image_digest:`` **dropped**.  Carrying the previous
    digest onto a new tag would silently pin the *old* image under a new
    version number — a reproducibility lie.  The digest is left for
    ``scripts/pin_digests.py`` (the registry's single digest authority) to
    fill when the candidate is applied; the old value is preserved under
    ``update_meta.previous_digest`` for traceability.
  * ``last_reviewed:`` set to today
  * ``update_meta.source: release_watch``

This script is read-only against the registry and the network; it
only writes to ``update/candidates/`` and ``update/release_watch_state.json``.

Network: stdlib only.  GitHub releases API (rate-limited to 60 req/hour
unauthenticated — set ``GITHUB_TOKEN`` to raise to 5000/hour) plus the
public quay.io tags API (no auth) to resolve BioContainers builds.

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
    """Best-effort tag rewrite used only when the real BioContainers build
    can't be resolved.  For ``foo/bar:1.2.3`` swap the tag; a build suffix
    (``--h12345_0``) is dropped, leaving a bare-version placeholder that a
    maintainer must confirm."""
    if ":" not in image:
        return image
    base, _ = image.rsplit(":", 1)
    return f"{base}:{new_version}"


_QUAY_BIOCONTAINERS = "quay.io/biocontainers/"


def _quay_repo(image: str) -> Optional[str]:
    """The repo name if *image* is a ``quay.io/biocontainers/`` image, else None."""
    if not image.startswith(_QUAY_BIOCONTAINERS):
        return None
    rest = image[len(_QUAY_BIOCONTAINERS):]
    return rest.split("@", 1)[0].split(":", 1)[0]


def _python_family(image: str) -> Optional[str]:
    """The ``pyNNN`` build family of a BioContainers tag, if it has one.

    ``…:1.3.0--py311heb3b1e3_0`` → ``py311``.  BioContainers ships one build
    per Python minor; we keep the family stable across a bump so a swap doesn't
    silently jump Python versions."""
    if ":" not in image:
        return None
    tag = image.rsplit(":", 1)[1]
    if "--" not in tag:
        return None
    m = re.match(r"(py\d+)", tag.split("--", 1)[1])
    return m.group(1) if m else None


def _quay_tags(repo: str, version: str, opener) -> list[dict]:
    """Active quay.io tags for *repo* whose version (before the ``--`` build
    suffix) is exactly *version*, each carrying a manifest digest."""
    from urllib.parse import quote
    url = (
        f"https://quay.io/api/v1/repository/biocontainers/{repo}/tag/"
        f"?onlyActiveTags=true&limit=100&filter_tag_name=like:{quote(version)}"
    )
    data = opener(url)
    out = []
    for t in data.get("tags", []):
        name = t.get("name", "")
        # exact version match — 'like:1.3.1' would also return 1.3.10
        if name.split("--", 1)[0] != version:
            continue
        if t.get("manifest_digest"):
            out.append(t)
    return out


def resolve_biocontainer_image(
    image: str, version: str, opener=None,
) -> Optional[str]:
    """Full ``quay.io/biocontainers/<repo>:<version>--<build>`` image string for
    *version*, preferring the current image's Python build family.  Returns None
    when *image* isn't a BioContainer, no build exists for *version* yet, or the
    quay API can't be reached."""
    repo = _quay_repo(image)
    if repo is None:
        return None
    opener = opener or _http_json
    try:
        tags = _quay_tags(repo, version, opener)
    except Exception:
        return None
    if not tags:
        return None
    fam = _python_family(image)
    if fam:
        same_family = [
            t for t in tags if t["name"].split("--", 1)[1].startswith(fam)
        ]
        if same_family:
            tags = same_family
    # newest build wins (quay's start_ts is descending-friendly; name breaks ties)
    tags.sort(key=lambda t: (t.get("start_ts") or 0, t["name"]), reverse=True)
    base = image.split("@", 1)[0].rsplit(":", 1)[0]
    return f"{base}:{tags[0]['name']}"


def make_candidate(
    tool_doc: dict, new_version: str, today: str, *, opener=None,
) -> dict:
    doc = dict(tool_doc)   # shallow copy is fine — we replace top-level keys
    doc["version"] = new_version
    container = dict(doc.get("container", {}))
    old_image = container.get("image", "")

    resolved = resolve_biocontainer_image(old_image, new_version, opener=opener)
    risks: list[str] = []
    if resolved:
        container["image"] = resolved
        tag_note = "Real BioContainers build resolved from quay.io."
    else:
        container["image"] = _bump_image_tag(old_image, new_version)
        if _quay_repo(old_image):
            tag_note = (
                "No BioContainers build for this version on quay.io yet — the "
                "tag is a best-effort guess; confirm before applying."
            )
            risks.append("unverified image tag")
        else:
            tag_note = (
                "Self-built / non-BioContainers image — build and push the new "
                "tag, then repin."
            )
            risks.append("image must be built and pushed")

    # NEVER carry the previous digest onto a new tag: it would pin the OLD image
    # under a new version number.  Drop it (keeping it for traceability) and let
    # scripts/pin_digests.py resolve the real one when the candidate is applied.
    previous_digest = container.pop("image_digest", None)
    risks.append("digest not pinned — run scripts/pin_digests.py after applying")

    doc["container"] = container
    doc["last_reviewed"] = today
    doc["update_meta"] = {
        "month": today[:7],
        "source": "release_watch",
        "previous_version": tool_doc.get("version"),
        "previous_image": tool_doc.get("container", {}).get("image"),
        "previous_digest": previous_digest,
        "note": "Auto-filed by update/release_watch.py. " + tag_note,
        "risks": risks,
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
