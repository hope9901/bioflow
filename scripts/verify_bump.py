#!/usr/bin/env python3
"""Behaviour gate for tool version bumps — run BEFORE you commit/push a bump.

The nightly full-pipeline e2e catches a broken bump, but only *after* it lands
on ``main`` (that's the failure email).  This runs the same class of check
locally, up front: for every bumped tool it launches the tool's **pinned
image** and exercises its real operation on a tiny generated input — catching
the "binary exists but silently produces garbage" break (e.g. the staphb
``prokka:1.15.6`` repackage that emitted 0 CDS) that a ``command -v`` liveness
probe cannot.

    # verify only what changed vs origin/main (default)
    python scripts/verify_bump.py

    # verify specific tools
    python scripts/verify_bump.py prokka bcftools gatk4

Exit code 0 = every bumped tool behaves; 1 = at least one is broken (do not
push).  Tools whose real op needs a large runtime database the recipe supplies
(kraken2/snpeff/checkm2/…) fall back to a liveness probe with a clear ``[live]``
tag — those still need the recipe's own e2e for a full check.

Requires a working Docker daemon; images are pulled on demand and removed after
each check to keep disk bounded.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "registry" / "tools"

# tool_id -> (kind, shell). ``real`` runs the tool's actual operation on a
# self-contained tiny input and must exit 0 with the expected artefact;
# ``live`` only probes the tool responds (its real op needs a big runtime DB).
# Keep the command list in sync with the recipe stage that uses the tool.
SMOKE: dict[str, tuple[str, str]] = {
    "bcftools": ("real",
        'printf "##fileformat=VCFv4.2\\n##contig=<ID=1>\\n#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\n1\\t100\\t.\\tA\\tT\\t50\\t.\\t.\\n" > t.vcf; '
        'bcftools view t.vcf | grep -q "\\t100\\t" && bcftools stats t.vcf | grep -q "number of SNPs"'),
    "bowtie2": ("real",
        'printf ">c\\nACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\\n" > r.fa; bowtie2-build r.fa idx >/dev/null 2>&1; '
        'printf "@r\\nACGTACGTACGTACGTACGT\\n+\\nIIIIIIIIIIIIIIIIIIII\\n" > q.fq; bowtie2 -x idx -U q.fq -S out.sam >/dev/null 2>&1; test -s out.sam'),
    "diamond": ("real",
        'printf ">p\\nMKVLTPEEKSAVTALWGKVNVDEVGGEALGRLLVVYPWTQRFFESFGDLST\\n" > p.faa; '
        'diamond makedb --in p.faa -d db >/dev/null 2>&1; diamond blastp -q p.faa -d db -o h.tsv >/dev/null 2>&1; test -s h.tsv'),
    "macs3": ("real",
        'i=1; while [ $i -le 200 ]; do printf "chr1\\t%d\\t%d\\t.\\t.\\t+\\n" $((i*10)) $((i*10+50)); i=$((i+1)); done > t.bed; '
        'macs3 callpeak -t t.bed -f BED -g 10000 --nomodel --extsize 100 -n s --outdir o >/dev/null 2>&1; ls o/s_peaks.* >/dev/null 2>&1'),
    "nanoplot": ("real",
        'i=1; while [ $i -le 30 ]; do printf "@r%d\\nACGTACGTACGTACGTACGTACGTACGTACGT\\n+\\nIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII\\n" $i; i=$((i+1)); done > q.fastq; '
        'NanoPlot --fastq q.fastq -o o >/dev/null 2>&1; ls o/NanoPlot-report.html >/dev/null 2>&1'),
    "picard": ("real",
        'printf ">c\\nACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\\n" > r.fa; picard CreateSequenceDictionary R=r.fa O=r.dict >/dev/null 2>&1; test -s r.dict'),
    "metabat2": ("live", 'metabat2 --help >/dev/null 2>&1'),
    "gatk4": ("live", 'gatk HaplotypeCaller --version >/dev/null 2>&1 || gatk --list >/dev/null 2>&1'),
    "snpeff": ("live", 'snpEff -version 2>&1 | grep -qiE "[0-9]"'),
    "checkm2": ("live", 'checkm2 --version >/dev/null 2>&1 && checkm2 predict --help >/dev/null 2>&1'),
    "compleasm": ("live", 'compleasm --version >/dev/null 2>&1 || compleasm -h >/dev/null 2>&1'),
    "flye": ("live", 'flye --version >/dev/null 2>&1'),
    "medaka": ("live", 'medaka --version >/dev/null 2>&1 && medaka_consensus -h >/dev/null 2>&1'),
    "bracken": ("live", 'bracken -h >/dev/null 2>&1'),
    "kraken2": ("live", 'kraken2 --version >/dev/null 2>&1 && kraken2-build --help >/dev/null 2>&1'),
    "percolator": ("live", 'percolator --help >/dev/null 2>&1'),
    "tobias": ("live", 'TOBIAS --version >/dev/null 2>&1 || TOBIAS --help >/dev/null 2>&1'),
}


def _registry() -> dict[str, dict]:
    reg = {}
    for p in TOOLS.rglob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        if d and "id" in d:
            reg[d["id"]] = d
    return reg


def _changed_tool_ids() -> list[str]:
    """Tool ids whose YAML changed vs origin/main (best effort)."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD", "--", "registry/tools"],
            cwd=str(ROOT), capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return []
    ids = []
    for line in out.splitlines():
        if line.endswith(".yaml"):
            ids.append(Path(line).stem)
    return ids


def _liveness(reg_entry: dict) -> str:
    """Fallback probe: first token of the command_template + --version/help."""
    tmpl = reg_entry.get("command_template", "") or ""
    m = re.search(r"([A-Za-z0-9_.\-]+)", tmpl)
    tok = m.group(1) if m else ""
    return (f'command -v {tok} >/dev/null 2>&1 && '
            f'({tok} --version >/dev/null 2>&1 || {tok} --help >/dev/null 2>&1 '
            f'|| {tok} -h >/dev/null 2>&1 || true)') if tok else "true"


RECIPES = ROOT / "bioflow" / "recipes"
E2E = ROOT / "tests" / "integration" / "test_full_pipeline_e2e.py"


def _recipes_with_e2e() -> set[str]:
    if not E2E.exists():
        return set()
    return set(re.findall(r"def test_([a-z_]+)_full_chain", E2E.read_text(encoding="utf-8")))


def _recipes_using(image: str) -> set[str]:
    """Registered recipe names whose @stage pins *image*."""
    names: set[str] = set()
    for p in RECIPES.rglob("*.py"):
        s = p.read_text(encoding="utf-8")
        if image and image in s:
            names.update(re.findall(r'register\("([a-z_]+)"', s))
    return names


def _run_affected_e2e(recipes: set[str]) -> bool:
    """Run the full-pipeline e2e for the given recipes (real Docker)."""
    if not recipes:
        return True
    k = " or ".join(sorted(recipes))
    print(f"\nrunning full e2e for affected covered recipe(s): {k}")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(E2E), "-m", "docker",
         "-k", k, "-q", "--no-header"],
        cwd=str(ROOT),
    )
    return r.returncode == 0


def _run_one(tid: str, image: str, kind: str, shell: str) -> bool:
    subprocess.run(["docker", "pull", "-q", image],
                   capture_output=True, text=True)
    r = subprocess.run(["docker", "run", "--rm", image, "sh", "-c", shell],
                       capture_output=True, text=True)
    ok = r.returncode == 0
    tag = f"[{kind}]"
    print(f"  {'PASS' if ok else 'FAIL'} {tag:6} {tid:14} {image.rsplit('/', 1)[-1]}")
    if not ok:
        for ln in (r.stdout + r.stderr).strip().splitlines()[-4:]:
            print(f"        {ln}")
    subprocess.run(["docker", "rmi", image], capture_output=True, text=True)
    return ok


def main(argv: list[str]) -> int:
    reg = _registry()
    ids = [a for a in argv[1:] if not a.startswith("-")] or _changed_tool_ids()
    ids = [t for t in dict.fromkeys(ids) if t in reg]
    if not ids:
        print("verify_bump: no changed tool YAMLs vs origin/main — nothing to check.")
        return 0

    print(f"verify_bump: behaviour-checking {len(ids)} tool(s) in their pinned images\n")
    failed = []
    e2e_recipes = _recipes_with_e2e()
    affected_e2e: set[str] = set()
    for tid in sorted(ids):
        image = (reg[tid].get("container") or {}).get("image", "")
        if not image:
            continue
        if tid in SMOKE:
            kind, shell = SMOKE[tid]
        else:
            kind, shell = "live", _liveness(reg[tid])
        if not _run_one(tid, image, kind, shell):
            failed.append(tid)
        # Any covered recipe that pins this tool gets its full e2e run too — the
        # reliable check for tools a synthetic smoke can't exercise (prokka).
        affected_e2e |= _recipes_using(image) & e2e_recipes

    if not _run_affected_e2e(affected_e2e):
        failed.append("<full-e2e>")

    print()
    if failed:
        print(f"::error::verify_bump FAILED for: {', '.join(failed)} — do NOT push.")
        return 1
    print(f"verify_bump OK — {len(ids)} tool(s) behave"
          + (f"; e2e green for {', '.join(sorted(affected_e2e))}" if affected_e2e else "")
          + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
