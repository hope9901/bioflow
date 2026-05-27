"""Daily registry freshness check (T1 cadence).

For every tool YAML in ``registry/tools/``:
  1. Resolve the container image's registry API
     (quay.io / Docker Hub / unknown).
  2. Check whether the pinned tag still exists (yanked detection).
  3. List the most recent tags and flag any that look newer than the
     pinned version.

Output: a Markdown report at
``update/notifications/freshness-<YYYY-MM-DD>.md``.

This script never modifies the registry — it only reports.  Its
purpose is to surface "silent decay":  upstream tag yanks,
BioContainers re-builds, or upstream releases that slipped past the
monthly Deep Research cycle.

It also reports how many days have passed since the last Cowork
candidate batch landed under ``update/candidates/`` — a long silence
there usually means the off-machine scheduler stopped firing.

Network: uses only ``urllib`` (stdlib).  If the network is
unreachable, the script still produces a report listing every tool as
``check_failed`` rather than crashing.

Usage::

    python -m update.freshness_check                  # default paths
    python -m update.freshness_check --out PATH       # custom report
    python -m update.freshness_check --registry DIR   # other registry root
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "registry" / "tools"
DEFAULT_NOTIFY_DIR = REPO_ROOT / "update" / "notifications"
DEFAULT_CANDIDATES_DIR = REPO_ROOT / "update" / "candidates"


# ---------------------------------------------------------------------------
# Image string parsing
# ---------------------------------------------------------------------------

_IMAGE_RE = re.compile(
    r"^(?:(?P<host>[^/]+)/)?(?P<owner>[^/]+)/(?P<name>[^:]+):(?P<tag>.+)$"
)
_FALLBACK_RE = re.compile(r"^(?P<owner>[^/:]+):(?P<tag>.+)$")  # busybox:latest


def parse_image(image: str) -> Optional[dict]:
    """Return {host, owner, name, tag} or None if unparseable.

    ``quay.io/biocontainers/fastp:0.23.4--h5f740d0_0`` →
        host=quay.io owner=biocontainers name=fastp tag=0.23.4--h5f740d0_0
    ``staphb/spades:4.0.0`` →
        host=None owner=staphb name=spades tag=4.0.0
    ``busybox:latest`` →
        host=None owner=library name=busybox tag=latest
    """
    m = _IMAGE_RE.match(image)
    if m:
        d = m.groupdict()
        host = d["host"]
        if host is None or "." not in host:
            # No registry prefix → assume Docker Hub
            return {
                "host": "docker.io",
                "owner": d["owner"],
                "name": d["name"],
                "tag": d["tag"],
            }
        return {
            "host": host,
            "owner": d["owner"],
            "name": d["name"],
            "tag": d["tag"],
        }
    m2 = _FALLBACK_RE.match(image)
    if m2:
        return {
            "host": "docker.io",
            "owner": "library",
            "name": m2.group("owner"),
            "tag": m2.group("tag"),
        }
    return None


# ---------------------------------------------------------------------------
# Registry-specific tag fetchers
# ---------------------------------------------------------------------------

def _http_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": "bioflow-freshness-check/0.1"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_tags_quay(owner: str, name: str, limit: int = 25) -> list[str]:
    """quay.io REST API.  Returns a list of tag names (newest first)."""
    url = (
        f"https://quay.io/api/v1/repository/{owner}/{name}/tag/"
        f"?limit={limit}&onlyActiveTags=true"
    )
    data = _http_json(url)
    # API returns {"tags": [{"name": ..., "last_modified": ...}, ...]}
    return [t["name"] for t in data.get("tags", [])]


def fetch_tags_dockerhub(owner: str, name: str, limit: int = 25) -> list[str]:
    """Docker Hub v2 API."""
    url = (
        f"https://hub.docker.com/v2/repositories/{owner}/{name}/tags"
        f"?page_size={limit}"
    )
    data = _http_json(url)
    return [t["name"] for t in data.get("results", [])]


def fetch_tags(parsed: dict, limit: int = 25) -> list[str]:
    if parsed["host"] == "quay.io":
        return fetch_tags_quay(parsed["owner"], parsed["name"], limit)
    if parsed["host"] == "docker.io":
        return fetch_tags_dockerhub(parsed["owner"], parsed["name"], limit)
    # Other registries: give up gracefully
    raise NotImplementedError(f"registry not supported: {parsed['host']}")


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------

_VERSION_PART_RE = re.compile(r"(\d+)|([a-zA-Z]+)")


def _version_key(s: str) -> tuple:
    """Loose lexicographic-numeric key for version comparison.

    Splits "1.2.3--build4" into [1, 2, 3, "build", 4] so simple
    upstream bumps sort correctly.  Non-numeric tags ("latest",
    "RELEASE_3_18") still sort, just not necessarily meaningfully.
    """
    parts = []
    for num, alpha in _VERSION_PART_RE.findall(s):
        if num:
            parts.append((0, int(num)))
        else:
            parts.append((1, alpha.lower()))
    return tuple(parts)


def find_newer_tags(current_tag: str, candidate_tags: Iterable[str]) -> list[str]:
    """Return candidates whose version key sorts strictly higher than
    *current_tag*.  Best-effort — for `latest`/`RELEASE_*` style tags the
    result may be empty even when something newer exists."""
    cur = _version_key(current_tag)
    out = []
    for t in candidate_tags:
        if t == current_tag:
            continue
        try:
            if _version_key(t) > cur:
                out.append(t)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Per-tool check
# ---------------------------------------------------------------------------

def check_tool(tool_path: Path) -> dict:
    """Return a record for one tool YAML."""
    doc = yaml.safe_load(tool_path.read_text(encoding="utf-8"))
    image = doc.get("container", {}).get("image", "")
    parsed = parse_image(image)
    rec: dict = {
        "tool_id": doc.get("id"),
        "version": doc.get("version"),
        "image": image,
        "status": "ok",
        "newer_tags": [],
        "note": "",
    }
    if not parsed:
        rec["status"] = "unparseable"
        rec["note"] = f"could not parse image string {image!r}"
        return rec

    try:
        tags = fetch_tags(parsed, limit=25)
    except NotImplementedError as e:
        rec["status"] = "skipped"
        rec["note"] = str(e)
        return rec
    except urllib.error.HTTPError as e:
        if e.code == 404:
            rec["status"] = "yanked"
            rec["note"] = f"image not found at {parsed['host']}"
        else:
            rec["status"] = "check_failed"
            rec["note"] = f"HTTP {e.code} from {parsed['host']}"
        return rec
    except Exception as e:
        rec["status"] = "check_failed"
        rec["note"] = f"{type(e).__name__}: {e}"
        return rec

    if parsed["tag"] not in tags:
        # Could be that the tag is older than the most-recent 25 — best
        # effort.  If it's a versioned tag and not in the recent list,
        # flag as `tag_aged_out` rather than yanked.
        rec["status"] = "tag_aged_out"
        rec["note"] = (
            f"current tag {parsed['tag']!r} not in the {len(tags)} most "
            f"recent tags — likely older than recent activity"
        )

    newer = find_newer_tags(parsed["tag"], tags)
    rec["newer_tags"] = newer[:5]   # cap report size
    if newer:
        if rec["status"] == "ok":
            rec["status"] = "update_available"
    return rec


# ---------------------------------------------------------------------------
# Cowork pulse check
# ---------------------------------------------------------------------------

def days_since_last_candidate(candidates_dir: Path) -> Optional[int]:
    """How many days since the newest candidate YAML landed?  None if
    the dir doesn't exist or has no YAMLs."""
    if not candidates_dir.exists():
        return None
    yamls = list(candidates_dir.rglob("*.yaml"))
    if not yamls:
        return None
    newest = max(p.stat().st_mtime for p in yamls)
    age = dt.datetime.now() - dt.datetime.fromtimestamp(newest)
    return max(0, age.days)   # filesystem clock skew can give -1; clamp


def days_since_last_t3_run(last_run_path: Path) -> Optional[int]:
    """How many days since `bioflow update auto` last produced a
    last_run.json?  None if the file doesn't exist (cron may never have
    run, or the maintainer hasn't installed the schedule)."""
    if not last_run_path.exists():
        return None
    age = dt.datetime.now() - dt.datetime.fromtimestamp(
        last_run_path.stat().st_mtime,
    )
    return max(0, age.days)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_report(
    records: list[dict],
    cowork_pulse: Optional[int],
    t3_pulse: Optional[int] = None,
) -> str:
    today = dt.date.today().isoformat()
    by_status: dict[str, list[dict]] = {}
    for r in records:
        by_status.setdefault(r["status"], []).append(r)

    lines = [f"# Registry freshness check — {today}", ""]

    def section(title: str, status: str):
        recs = by_status.get(status, [])
        lines.append(f"## {title} ({len(recs)})")
        if not recs:
            lines.append("- none")
        else:
            for r in sorted(recs, key=lambda x: x["tool_id"] or ""):
                if r["newer_tags"]:
                    new = ", ".join(r["newer_tags"])
                    lines.append(
                        f"- `{r['tool_id']}` {r['version']} → newer: {new}  "
                        f"_(image: {r['image']})_"
                    )
                else:
                    lines.append(
                        f"- `{r['tool_id']}` {r['version']} — {r['note']}  "
                        f"_(image: {r['image']})_"
                    )
        lines.append("")

    section("Newer tags available",          "update_available")
    section("Yanked / image not found",       "yanked")
    section("Current tag aged out of recent", "tag_aged_out")
    section("Check failed (network / API)",   "check_failed")
    section("Skipped (unsupported registry)", "skipped")
    section("Unparseable image string",       "unparseable")
    section("Up to date",                     "ok")

    lines.append("## Scheduler pulses")
    if cowork_pulse is None:
        lines.append("- ⚠️  Cowork: no candidate YAMLs found under "
                     "`update/candidates/` — pipeline may have stopped firing")
    elif cowork_pulse > 35:
        lines.append(f"- ⚠️  Cowork: last candidate landed **{cowork_pulse} "
                     "days ago** — expected ≤30 (monthly cadence). Investigate.")
    else:
        lines.append(f"- ✓ Cowork: last candidate landed {cowork_pulse} "
                     "days ago (within expected monthly cadence)")

    if t3_pulse is None:
        lines.append("- ⚠️  T3 local cron: `update/last_run.json` not found — "
                     "`bioflow update auto` has never run on this machine "
                     "(see scripts/install-schedule-windows.ps1 / cron.sh)")
    elif t3_pulse > 35:
        lines.append(f"- ⚠️  T3 local cron: last ran **{t3_pulse} days ago** "
                     "— expected ≤30. Schedule may be unregistered or failing.")
    else:
        lines.append(f"- ✓ T3 local cron: last ran {t3_pulse} days ago")
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- Tools checked: {len(records)}")
    lines.append(
        f"- Newer upstream: {len(by_status.get('update_available', []))}"
    )
    lines.append(f"- Yanked: {len(by_status.get('yanked', []))}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="freshness_check",
        description="Daily registry-image freshness check.",
    )
    ap.add_argument(
        "--registry", type=Path, default=DEFAULT_REGISTRY,
        help=f"Root of registry/tools (default: {DEFAULT_REGISTRY}).",
    )
    ap.add_argument(
        "--candidates-dir", type=Path, default=DEFAULT_CANDIDATES_DIR,
        help="Where Cowork drops monthly candidate YAMLs.",
    )
    ap.add_argument(
        "--out", type=Path, default=None,
        help="Report file path "
             "(default: update/notifications/freshness-<DATE>.md).",
    )
    args = ap.parse_args(argv)

    tool_files = sorted(args.registry.rglob("*.yaml"))
    records = [check_tool(p) for p in tool_files]
    pulse = days_since_last_candidate(args.candidates_dir)
    t3_pulse = days_since_last_t3_run(REPO_ROOT / "update" / "last_run.json")
    report = render_report(records, pulse, t3_pulse=t3_pulse)

    out = args.out
    if out is None:
        DEFAULT_NOTIFY_DIR.mkdir(parents=True, exist_ok=True)
        out = DEFAULT_NOTIFY_DIR / f"freshness-{dt.date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Wrote report → {out}")

    n_updates = sum(1 for r in records if r["status"] == "update_available")
    n_yanked  = sum(1 for r in records if r["status"] == "yanked")
    # exit code: 0 = clean, 1 = updates available, 2 = yanked (more urgent)
    if n_yanked:
        return 2
    if n_updates:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
