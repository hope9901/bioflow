"""Pin container image digests into every tool YAML.

For each ``registry/tools/**/*.yaml`` whose ``container.image`` is not
already digest-pinned, this script:

  1. resolves the host-architecture manifest digest via
     ``docker manifest inspect <image>`` (works without a local pull),
  2. writes ``container.image_digest: sha256:…`` back into the YAML,
  3. preserves comments / order via ruamel.yaml when available, falling
     back to PyYAML otherwise.

Usage
-----
::

    # Pin every tool that lacks a digest:
    python scripts/pin_digests.py

    # Re-pin specific tools (overwrite existing digests):
    python scripts/pin_digests.py --force fastp spades

    # Dry-run — print what would change without touching files:
    python scripts/pin_digests.py --dry-run

    # Audit-only — exit 1 if any tool YAML lacks a digest:
    python scripts/pin_digests.py --audit

The script never edits YAMLs whose ``container.image`` cannot be
resolved (missing tag, registry timeout, etc.) — it logs the failure
and moves on.  Re-run after fixing network access.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "tools"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# YAML I/O — prefer ruamel.yaml to keep comments / key order
# ---------------------------------------------------------------------------

def _load_yaml(path: Path):
    try:
        from ruamel.yaml import YAML  # type: ignore[import-not-found]

        yaml = YAML()
        yaml.preserve_quotes = True
        yaml.indent(mapping=2, sequence=4, offset=2)
        # Disable line-wrapping so the 71-char sha256 string stays on one
        # line (default width is 80).  The schema requires a single
        # ``sha256:<64hex>`` token; folded values still parse but read
        # ugly in `git diff`.
        yaml.width = 4096
        with path.open("r", encoding="utf-8") as f:
            return yaml.load(f), yaml
    except ImportError:
        import yaml  # type: ignore[import-not-found]

        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f), None


def _dump_yaml(path: Path, data, yaml_obj=None) -> None:
    if yaml_obj is not None:
        with path.open("w", encoding="utf-8") as f:
            yaml_obj.dump(data, f)
    else:
        import yaml  # type: ignore[import-not-found]

        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)


# ---------------------------------------------------------------------------
# Docker manifest resolution
# ---------------------------------------------------------------------------

def _resolve_digest(image: str) -> str | None:
    """Return the host-architecture sha256 digest for *image*, or None on failure."""
    if "@sha256:" in image:
        # already digest-pinned via the image string itself
        return image.split("@", 1)[1]

    if shutil.which("docker") is None:
        print("ERROR: docker CLI not on PATH", file=sys.stderr)
        return None

    # First try `docker buildx imagetools inspect --raw` (works for OCI / multi-arch
    # indexes and returns JSON without pulling the image).  Falls back to
    # `docker manifest inspect` if buildx is unavailable.
    for cmd in (
        ["docker", "buildx", "imagetools", "inspect", "--raw", image],
        ["docker", "manifest", "inspect", image],
    ):
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  {image}: {' '.join(cmd[:3])} errored: {exc}", file=sys.stderr)
            continue
        if r.returncode != 0:
            continue
        digest = _digest_from_manifest(r.stdout, image)
        if digest:
            return digest

    # Last resort: pull then inspect locally (slow, costs bandwidth).
    return _resolve_via_pull(image)


def _digest_from_manifest(raw: str, image: str) -> str | None:
    """Extract a host-architecture digest from a manifest JSON blob.

    For a multi-arch index, walk ``manifests[].platform`` and pick
    linux/amd64 (the canonical bioflow runtime).  For a single-arch
    manifest the top-level ``config.digest`` is not what we want — we
    need the manifest digest itself, which we obtain by hashing the
    raw bytes (``docker manifest inspect`` doesn't expose it directly).
    """
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # OCI image index / Docker manifest list
    if "manifests" in doc and isinstance(doc["manifests"], list):
        for m in doc["manifests"]:
            plat = m.get("platform", {})
            if plat.get("os") == "linux" and plat.get("architecture") == "amd64":
                d = m.get("digest")
                if d and DIGEST_RE.match(d):
                    return d
        # No linux/amd64 — return the first as a fallback
        for m in doc["manifests"]:
            d = m.get("digest")
            if d and DIGEST_RE.match(d):
                return d
        return None

    # Single-arch manifest — hash the raw payload to derive the manifest
    # digest (this is what `docker pull` reports).  Need the original
    # bytes; the buildx --raw stream is already that, so hash it.
    import hashlib

    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    candidate = f"sha256:{h}"
    if DIGEST_RE.match(candidate):
        return candidate
    return None


def _resolve_via_pull(image: str) -> str | None:
    """Pull the image then read RepoDigests — slow but reliable."""
    pull = subprocess.run(
        ["docker", "pull", image],
        capture_output=True, text=True, timeout=600, check=False,
    )
    if pull.returncode != 0:
        return None
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{json .RepoDigests}}", image],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if inspect.returncode != 0:
        return None
    try:
        repo_digests = json.loads(inspect.stdout)
    except json.JSONDecodeError:
        return None
    for rd in repo_digests:
        if "@sha256:" in rd:
            digest = rd.split("@", 1)[1]
            if DIGEST_RE.match(digest):
                return digest
    return None


# ---------------------------------------------------------------------------
# Per-YAML logic
# ---------------------------------------------------------------------------

def _iter_yamls(only: list[str] | None) -> list[Path]:
    paths = sorted(REGISTRY.rglob("*.yaml"))
    if only:
        paths = [p for p in paths if p.stem in only]
    return paths


def pin_one(
    path: Path,
    *,
    force: bool,
    dry_run: bool,
) -> tuple[str, str]:
    """Return (status, message) for one YAML.  Status ∈ {pinned, kept, fail, skip}."""
    data, yaml_obj = _load_yaml(path)
    if not isinstance(data, dict):
        return ("skip", "non-mapping document")

    container = data.get("container") or {}
    image = container.get("image")
    if not image:
        return ("skip", "no container.image")

    existing = container.get("image_digest")
    if existing and not force:
        return ("kept", f"already pinned ({existing[:19]}…)")

    digest = _resolve_digest(image)
    if not digest:
        return ("fail", f"could not resolve digest for {image}")
    if existing == digest and not force:
        return ("kept", "digest unchanged")

    if dry_run:
        return ("pinned", f"would set {digest[:19]}… (dry-run)")

    container["image_digest"] = digest
    data["container"] = container
    _dump_yaml(path, data, yaml_obj)
    return ("pinned", f"set {digest[:19]}…")


# ---------------------------------------------------------------------------
# Audit + CLI entry point
# ---------------------------------------------------------------------------

def audit() -> int:
    """Return number of tool YAMLs lacking a digest.  Print a one-line summary."""
    missing: list[str] = []
    pinned: list[str] = []
    for p in _iter_yamls(only=None):
        data, _ = _load_yaml(p)
        if not isinstance(data, dict):
            continue
        container = data.get("container") or {}
        digest = container.get("image_digest")
        if digest and DIGEST_RE.match(digest):
            pinned.append(p.stem)
        else:
            missing.append(p.stem)
    total = len(missing) + len(pinned)
    print(
        f"digest audit: {len(pinned)}/{total} pinned, {len(missing)} missing"
    )
    if missing and len(missing) <= 30:
        print("  missing:", ", ".join(missing))
    return len(missing)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument(
        "tools", nargs="*",
        help="Optional tool stems (file names without .yaml) to limit the run.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Re-pin even if an image_digest is already set.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print actions without writing YAMLs.",
    )
    p.add_argument(
        "--audit", action="store_true",
        help="Only count missing digests; exit 1 if any are missing.",
    )
    args = p.parse_args(argv)

    if args.audit:
        sys.exit(0 if audit() == 0 else 1)

    paths = _iter_yamls(args.tools or None)
    if not paths:
        print(f"No YAMLs matched under {REGISTRY}", file=sys.stderr)
        return 1

    counts = {"pinned": 0, "kept": 0, "fail": 0, "skip": 0}
    for path in paths:
        status, msg = pin_one(path, force=args.force, dry_run=args.dry_run)
        counts[status] = counts.get(status, 0) + 1
        prefix = {
            "pinned": "PIN ",
            "kept":   "OK  ",
            "fail":   "FAIL",
            "skip":   "skip",
        }[status]
        print(f"  {prefix}  {path.relative_to(REGISTRY.parent.parent)}  {msg}")

    print(
        f"\nSummary: pinned={counts['pinned']} kept={counts['kept']} "
        f"fail={counts['fail']} skip={counts['skip']}"
    )
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
