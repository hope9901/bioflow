# bioflow

A bioinformatics **SDK + cookbook** for one-line genomics analyses on a
single workstation with local Docker.  Each tool runs in its own
container (no native installs), each recipe is one CLI call, and a
privacy-first LLM companion is available when you want it.

[Install](install.md){ .md-button .md-button--primary }
[Quick start](quickstart.md){ .md-button }
[Browse recipes](reference/recipes.md){ .md-button }

---

## What you get

- **20 cookbook recipes** invokable as one-liners — assembly (prokaryote
  short-read + eukaryote long-read), RNA-seq DEG, metagenomics
  (profiling + assembly/binning), scRNA-seq, ChIP-seq, ATAC-seq,
  bisulfite methylation, LC-MS/MS proteomics, **variant calling**
  (single-sample + GATK cohort joint genotyping), and 8
  comparative-genomics analyses.
- **110 tools** registered across 16 categories, all pulled as
  BioContainer images at run time — nothing to install on the host
  beyond Docker + Python.
- **Hardware-aware**: every tool is classified `installable` /
  `runnable_slow` / `incompatible` against your CPU / RAM / GPU / arch.
- **Input-hash caching**: re-running a recipe with unchanged inputs
  returns in seconds.
- **Privacy-first LLM companion** (optional): terminology Q&A, sanitized
  error diagnosis, tool-registration assist.  Disabled by default.

## Two ways to use it

| | Recipe (`bioflow recipe run`) | Preset (`bioflow recommend --preset`) |
|---|---|---|
| **Defined in** | Python (`@stage` + `@pipeline`) | YAML (declarative tool chain) |
| **Best for** | Active execution, tuning, custom logic | Picking the recommended chain for this host |

## Design philosophy

bioflow is intentionally scoped to **one workstation + local Docker**.
HPC/SLURM, multi-user auth, and web dashboards are explicitly out of
scope — see the [design notes](DESIGN.md).

The registry stays fresh through a [5-tier update model](maintainer/UPDATE_CADENCES.md)
(daily image-freshness check, weekly GitHub release-watch, monthly
benchmark+promote, quarterly deprecation audit, PR-triggered smoke test).
