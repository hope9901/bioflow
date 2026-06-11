"""Concordance harness — bioflow vs. nf-core on the same input.

Purpose
-------
The single strongest credibility signal bioflow can offer is: *given the
same reads and reference, do bioflow's recipes produce the same calls as
the community-standard nf-core pipelines?*  This script computes that
concordance for the two output types that matter most:

* **VCF** (germline_variants / joint_genotyping  vs  nf-core/sarek):
  Jaccard over normalised ``CHROM:POS:REF:ALT`` keys, plus genotype
  concordance on the shared sites.
* **Count matrix** (rnaseq_deg  vs  nf-core/rnaseq):
  Spearman correlation of per-gene counts on shared genes.

What this script is and isn't
-----------------------------
It is the **comparison half** — it takes two already-produced outputs and
scores their agreement, emitting a JSON + a one-line summary.  It does
**not** run either pipeline: a full nf-core/sarek run needs tens of GB of
iGenomes references and hours of compute that don't belong in this repo's
CI.  The intended workflow is documented in
``docs/benchmarks/nfcore-concordance.md``: run both pipelines on a golden
dataset on a machine that has the references, then point this script at
the two outputs.  ``.github/workflows/nfcore-concordance.yml`` wires it
up as a manually-dispatched job for maintainers who have that machine.

Usage
-----
::

    # VCF concordance
    python scripts/compare_nfcore.py vcf \
        --bioflow out/cohort.filtered.vcf.gz \
        --reference sarek/joint.vcf.gz \
        --out concordance_vcf.json

    # Count-matrix concordance
    python scripts/compare_nfcore.py counts \
        --bioflow out/salmon.merged.counts.tsv \
        --reference nfcore/salmon.merged.gene_counts.tsv \
        --out concordance_counts.json

No third-party deps: VCF parsing and Spearman are implemented on stdlib.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# VCF concordance
# ---------------------------------------------------------------------------

def _open_text(path: Path):
    p = Path(path)
    if p.suffix == ".gz":
        return gzip.open(p, "rt", encoding="utf-8")
    return p.open("r", encoding="utf-8")


def _read_vcf_sites(path: Path, pass_only: bool) -> "dict[str, str]":
    """Return {``CHROM:POS:REF:ALT``: first-sample GT} for each record.

    Multi-allelic ALTs are split so each allele is keyed independently.
    Genotype is taken from the first sample column (or ``"."`` when the
    VCF is sites-only).
    """
    sites: dict[str, str] = {}
    with _open_text(path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 5:
                continue
            chrom, pos, _id, ref, alt = cols[:5]
            filt = cols[6] if len(cols) > 6 else "."
            if pass_only and filt not in (".", "PASS"):
                continue
            gt = "."
            if len(cols) >= 10:
                gt = cols[9].split(":", 1)[0]
            for a in alt.split(","):
                sites[f"{chrom}:{pos}:{ref}:{a}"] = gt
    return sites


def compare_vcf(bioflow: Path, reference: Path, *, pass_only: bool = True) -> dict:
    a = _read_vcf_sites(bioflow, pass_only)
    b = _read_vcf_sites(reference, pass_only)
    keys_a, keys_b = set(a), set(b)
    shared = keys_a & keys_b
    union = keys_a | keys_b
    jaccard = len(shared) / len(union) if union else 1.0
    gt_match = sum(1 for k in shared if a[k] == b[k])
    gt_conc = gt_match / len(shared) if shared else 0.0
    return {
        "type": "vcf",
        "bioflow_variants": len(keys_a),
        "reference_variants": len(keys_b),
        "shared": len(shared),
        "bioflow_only": len(keys_a - keys_b),
        "reference_only": len(keys_b - keys_a),
        "jaccard": round(jaccard, 4),
        "genotype_concordance_on_shared": round(gt_conc, 4),
        "pass_only": pass_only,
    }


# ---------------------------------------------------------------------------
# Count-matrix concordance (Spearman, stdlib)
# ---------------------------------------------------------------------------

def _read_counts(path: Path) -> "dict[str, float]":
    """Return {gene_id: count} from a 2+-column TSV (gene id, then the
    first numeric column).  Header lines and non-numeric rows skipped."""
    out: dict[str, float] = {}
    with _open_text(path) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            gene = parts[0]
            try:
                out[gene] = float(parts[1])
            except ValueError:
                continue   # header / non-numeric
    return out


def _rank(values: "list[float]") -> "list[float]":
    """Average-rank the values (ties share the mean rank)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: "list[float]", ys: "list[float]") -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    rx, ry = _rank(xs), _rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / (vx * vy)


def compare_counts(bioflow: Path, reference: Path) -> dict:
    a = _read_counts(bioflow)
    b = _read_counts(reference)
    shared = sorted(set(a) & set(b))
    xs = [a[g] for g in shared]
    ys = [b[g] for g in shared]
    rho = _spearman(xs, ys)
    return {
        "type": "counts",
        "bioflow_genes": len(a),
        "reference_genes": len(b),
        "shared_genes": len(shared),
        "spearman_rho": None if math.isnan(rho) else round(rho, 4),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = p.add_subparsers(dest="kind", required=True)

    pv = sub.add_parser("vcf", help="VCF concordance (vs nf-core/sarek)")
    pv.add_argument("--bioflow", type=Path, required=True)
    pv.add_argument("--reference", type=Path, required=True)
    pv.add_argument("--all-filters", action="store_true",
                    help="Include non-PASS records (default: PASS/. only).")
    pv.add_argument("--out", type=Path)
    pv.add_argument("--min-jaccard", type=float, default=None,
                    help="Exit non-zero if Jaccard is below this threshold.")

    pc = sub.add_parser("counts", help="Count-matrix concordance (vs nf-core/rnaseq)")
    pc.add_argument("--bioflow", type=Path, required=True)
    pc.add_argument("--reference", type=Path, required=True)
    pc.add_argument("--out", type=Path)
    pc.add_argument("--min-rho", type=float, default=None,
                    help="Exit non-zero if Spearman rho is below this threshold.")

    args = p.parse_args(argv)

    if args.kind == "vcf":
        result = compare_vcf(args.bioflow, args.reference,
                             pass_only=not args.all_filters)
        gate = ("min_jaccard", args.min_jaccard, result["jaccard"])
    else:
        result = compare_counts(args.bioflow, args.reference)
        gate = ("min_rho", args.min_rho, result.get("spearman_rho"))

    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)

    # Optional threshold gate for CI.
    _name, threshold, value = gate
    if threshold is not None:
        if value is None or value < threshold:
            print(f"FAIL: {_name}={threshold} but got {value}", file=sys.stderr)
            return 1
        print(f"OK: {value} >= {_name} {threshold}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
