#!/usr/bin/env python3
"""Batch-bump registry tools to a target version, resolving the *real* newest
build tag from the upstream registry (quay biocontainers / Docker Hub).

Freshness only lists tags; some are numeric-sort artifacts (kraken2 "2.17",
trim-galore "2.3.0" are not real releases) so we pick the newest build tag that
matches an explicit TARGET version we curated.  For each tool this:

  * finds the newest tag on the image's own registry whose version == TARGET,
  * rewrites the YAML image tag + version + last_reviewed,
  * rewrites the same image string in any recipe that pins it (lockstep).

Then run ``python scripts/pin_digests.py --force <ids...>`` to resolve digests,
and ``python scripts/io_contracts.py update`` to re-bless the contracts.

    python scripts/bump_tools.py --dry-run     # print the resolved plan
    python scripts/bump_tools.py               # apply the edits
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "registry" / "tools"
RECIPES = ROOT / "bioflow" / "recipes"

# tool_id -> target clean version.  Curated: landmine tags (kraken2/trim-galore
# phantom 2.x) capped to the real newest; genuinely risky recipe majors
# (bracken 3, medaka 2) and un-versioned tags (msconvert) are intentionally
# omitted here and tracked for individual e2e verification instead.
TARGETS: dict[str, str] = {
    # ── recipe-used ───────────────────────────────────────────────
    "abricate": "1.4.0", "bandage": "0.9.0", "bcftools": "1.23.1",
    "bismark": "0.25.1", "bowtie2": "2.5.5", "checkm2": "1.1.0",
    "compleasm": "0.2.8", "diamond": "2.2.2", "enrichr": "1.3.0",
    "gseapy": "1.3.0", "flye": "2.9.6", "gatk4": "4.6.2.0",
    "iqtree": "2.4.0", "macs3": "3.0.4", "metabat2": "2.18",
    "percolator": "3.9", "picard": "3.4.0", "prokka": "1.15.6",
    "quast": "5.3.0", "snpeff": "5.4", "spades": "4.2.0",
    "tobias": "0.17.3", "kraken2": "2.1.6", "trimgalore": "0.6.11",
    "mafft": "7.526", "multiqc": "1.35", "nanoplot": "1.47.1",
    # ── catalog-only ──────────────────────────────────────────────
    "abyss": "2.3.10", "braker3": "3.1.1", "bustools": "0.45.1",
    "bwa": "0.7.19", "bwa_mem2": "2.3", "canu": "2.3",
    "deeptools": "3.5.6", "eggnog_mapper": "2.1.15", "filtlong": "0.3.1",
    "freebayes": "1.3.10", "gfastats": "1.3.11", "hisat2": "2.2.2",
    "kallisto": "0.52.0", "kneaddata": "0.12.4", "masurca": "4.1.4",
    "metaphlan4": "4.2.4", "raven": "1.8.3", "skani": "0.3.2",
    "subread": "2.1.1", "verkko": "2.3.2", "antismash": "8.0.4",
    "bakta": "1.12.0", "busco": "6.1.0", "cellranger": "9.0.1",
    "cutadapt": "5.2", "dbcan": "5.2.9", "earlgrey": "7.2.6",
    "gtdbtk": "2.7.2", "harmony": "2.0.0", "hifiasm": "0.25.0",
    "minimap2": "2.31", "openms": "3.5.0", "samtools": "1.23.1",
    "seqkit": "2.13.0", "seurat": "5.5.1", "shasta": "0.14.0",
    "stringtie": "3.0.3",
}


def _vt(s: str) -> tuple:
    nums = re.findall(r"\d+", s.split("--")[0])
    return tuple(int(x) for x in nums)


def _quay_tags(pkg: str) -> list[str]:
    u = f"https://quay.io/api/v1/repository/biocontainers/{pkg}/tag/?limit=100&onlyActiveTags=true"
    d = json.load(urllib.request.urlopen(u, timeout=30))
    return [t["name"] for t in d.get("tags", [])]


def _dockerhub_tags(repo: str) -> list[str]:
    # repo like "staphb/spades" or "satijalab/seurat"
    u = f"https://hub.docker.com/v2/repositories/{repo}/tags/?page_size=100"
    d = json.load(urllib.request.urlopen(u, timeout=30))
    return [t["name"] for t in d.get("results", [])]


def _pick_tag(image: str, target: str) -> str | None:
    """Newest tag on *image*'s registry whose version matches *target*."""
    repo = image.rsplit(":", 1)[0]
    tgt = _vt(target)
    if repo.startswith("quay.io/biocontainers/"):
        pkg = repo.split("/")[-1]
        tags = _quay_tags(pkg)
    else:
        tags = _dockerhub_tags(repo.replace("docker.io/", ""))
    matches = [t for t in tags if _vt(t)[: len(tgt)] == tgt and t not in ("latest", "develop")]
    if not matches:
        return None
    # BioContainers publishes immutable build tags (``--<hash>_<n>``); prefer
    # those over a bare/mutable convenience tag so the pin stays reproducible.
    if repo.startswith("quay.io/biocontainers/"):
        immutable = [t for t in matches if "--" in t]
        if immutable:
            matches = immutable

    def _build(t: str) -> int:
        m = re.search(r"_(\d+)$", t)
        return int(m.group(1)) if m else -1

    # Prefer a clean release tag (version tuple exactly the target length) over
    # a git-describe dev tag like "2.18_23_gc869c52"; break ties by build number.
    exact = [t for t in matches if len(_vt(t.split("--")[0])) == len(tgt)]
    pool = exact or matches
    pool.sort(key=lambda t: (_vt(t.split("--")[0]), _build(t)), reverse=True)
    return pool[0]


def _registry() -> dict[str, tuple[Path, str, str]]:
    reg = {}
    for p in TOOLS.rglob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        if d and "id" in d:
            reg[d["id"]] = (p, str(d.get("version", "")),
                            (d.get("container") or {}).get("image", ""))
    return reg


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    reg = _registry()
    today = _dt.date.today().isoformat()
    plan, skipped = [], []
    for tid, target in sorted(TARGETS.items()):
        if tid not in reg:
            skipped.append((tid, "not in registry"))
            continue
        path, curver, image = reg[tid]
        repo = image.rsplit(":", 1)[0]
        curtag = image.rsplit(":", 1)[1] if ":" in image else ""
        try:
            newtag = _pick_tag(image, target)
        except Exception as e:  # network / API hiccup
            skipped.append((tid, f"resolve failed: {e}"))
            continue
        if not newtag:
            skipped.append((tid, f"no tag matching {target} on {repo}"))
            continue
        if newtag == curtag:
            skipped.append((tid, f"already at {newtag}"))
            continue
        new_image = f"{repo}:{newtag}"
        # Honest version label derived from the pinned tag (not the search
        # target), so we never reintroduce a label-vs-image mismatch.
        new_version = newtag.split("--")[0].lstrip("v")
        plan.append((tid, path, image, new_image, curver, new_version))

    print(f"{'tool':16} {'cur':14} -> {'new version':14} tag")
    print("-" * 78)
    for tid, path, image, new_image, curver, new_version in plan:
        print(f"{tid:16} {curver:14} -> {new_version:14} {new_image.rsplit('/',1)[-1]}")
    if skipped:
        print("\nskipped:")
        for tid, why in skipped:
            print(f"  {tid:16} {why}")
    print(f"\n{len(plan)} to bump, {len(skipped)} skipped")

    if dry:
        return 0

    bumped_ids = []
    for tid, path, image, new_image, curver, new_version in plan:
        t = path.read_text(encoding="utf-8")
        t = t.replace(image, new_image)  # image: line (and any inline)
        t = re.sub(r'(^version:\s*)"?[^"\n]*"?', rf'\g<1>"{new_version}"', t, count=1, flags=re.M)
        t = re.sub(r'(^last_reviewed:\s*)"?[^"\n]*"?', rf'\g<1>"{today}"', t, count=1, flags=re.M)
        path.write_text(t, encoding="utf-8")
        n = 0
        for rp in RECIPES.rglob("*.py"):
            s = rp.read_text(encoding="utf-8")
            if image in s:
                rp.write_text(s.replace(image, new_image), encoding="utf-8")
                n += 1
        bumped_ids.append(tid)
        print(f"bumped {tid} -> {new_image}" + (f"  ({n} recipe file(s))" if n else ""))

    print("\nnext:")
    print("  python scripts/pin_digests.py --force " + " ".join(bumped_ids))
    print("  python scripts/io_contracts.py update && python scripts/gen_docs.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
