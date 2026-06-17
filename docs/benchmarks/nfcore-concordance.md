# nf-core concordance benchmark

> **Claim under test**: given the *same* reads and reference, do bioflow's
> recipes produce the same calls as the community-standard nf-core
> pipelines?  This page defines the golden datasets, the method, and the
> acceptance thresholds.  The scoring harness is
> [`scripts/compare_nfcore.py`](https://github.com/hope9901/bioflow/blob/main/scripts/compare_nfcore.py).

## Why this matters

bioflow's recipes are deliberately small and readable, which invites the
fair question: *are they actually correct, or just toy examples?*  The
honest answer is a number — concordance against the pipeline reviewers
already trust.  This benchmark produces that number reproducibly.

## Scope & honesty note

A full nf-core/sarek or nf-core/rnaseq run needs tens of GB of iGenomes
references and hours of compute, which **do not belong in this repo's
CI**.  So this benchmark is split:

| Half | Where it runs | In this repo? |
|---|---|---|
| Produce the two outputs (bioflow + nf-core) | a machine with the references | no (operator-run) |
| **Score their agreement** | anywhere — pure stdlib | **yes** (`compare_nfcore.py`, unit-tested) |

The scoring half is committed, tested, and CI-wired (manual dispatch).
The production half is documented here so any maintainer with the
references can reproduce the numbers; the resulting JSON is then attached
to the release.

## Golden datasets

| Comparison | bioflow recipe | nf-core pipeline | Dataset |
|---|---|---|---|
| Germline SNV/indel | `germline_variants` / `joint_genotyping` | `nf-core/sarek` | GIAB **HG002** chr20, GRCh38 (subset to ~50× chr20) |
| RNA-seq quantification | `rnaseq_deg` | `nf-core/rnaseq` | nf-core test data (`SRR6357070-3`), GRCh38 chr22 |

GIAB HG002 is the natural variant-calling truth set; chr20/chr22 subsets
keep each run to minutes-to-an-hour on a workstation while remaining
biologically real.

## Method

### VCF (variant calling)

1. Run `bioflow recipe run germline_variants` (or `joint_genotyping`) and
   `nf-core/sarek` on the same FASTQs + GRCh38.
2. Score:
   ```bash
   python scripts/compare_nfcore.py vcf \
     --bioflow out/cohort.filtered.vcf.gz \
     --reference sarek/joint.vcf.gz \
     --out concordance_vcf.json --min-jaccard 0.90
   ```
3. Metrics: **Jaccard** over normalised `CHROM:POS:REF:ALT` (multi-allelic
   split), and **genotype concordance** on the shared sites.

### Count matrix (RNA-seq)

1. Run `bioflow recipe run rnaseq_deg` and `nf-core/rnaseq` on the same
   FASTQs + transcriptome.
2. Score:
   ```bash
   python scripts/compare_nfcore.py counts \
     --bioflow out/salmon.merged.counts.tsv \
     --reference nfcore/salmon.merged.gene_counts.tsv \
     --out concordance_counts.json --min-rho 0.95
   ```
3. Metric: **Spearman ρ** of per-gene counts on shared genes.

## Acceptance thresholds (initial)

| Metric | Threshold | Rationale |
|---|---:|---|
| VCF Jaccard (PASS) | ≥ 0.90 | Different callers legitimately disagree at the margins; >0.9 means the core call set matches. |
| Genotype concordance | ≥ 0.98 | On shared sites the genotype should almost always agree. |
| RNA-seq Spearman ρ | ≥ 0.95 | Salmon-vs-Salmon quant should be near-identical; ρ captures aligner/index differences. |

These are starting points — the first real run calibrates them, and the
agreed values become the CI gate.

## Running it (operator)

See [`.github/workflows/nfcore-concordance.yml`](https://github.com/hope9901/bioflow/blob/main/.github/workflows/nfcore-concordance.yml)
— a `workflow_dispatch` job that expects a self-hosted runner (or a large
GitHub runner) with the references staged, runs both pipelines, and
invokes the harness with the thresholds above.  The job is **not** part
of the per-PR gate; it is run deliberately before a release and its JSON
output is published with the release notes.
