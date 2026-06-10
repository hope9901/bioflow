# bioflow

[![PyPI](https://img.shields.io/pypi/v/bioflowkit.svg)](https://pypi.org/project/bioflowkit/)
[![Downloads](https://img.shields.io/pypi/dm/bioflowkit.svg)](https://pypi.org/project/bioflowkit/)
[![python](https://img.shields.io/pypi/pyversions/bioflowkit.svg)](https://pypi.org/project/bioflowkit/)
[![tests](https://img.shields.io/badge/tests-565%20passed-brightgreen)](tests/)
[![nightly smoke](https://github.com/hope9901/bioflow/actions/workflows/nightly-smoke.yml/badge.svg)](https://github.com/hope9901/bioflow/actions/workflows/nightly-smoke.yml)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
[![docs](https://img.shields.io/badge/docs-mkdocs-blue)](https://hope9901.github.io/bioflow/)

📖 **Documentation: https://hope9901.github.io/bioflow/**

A bioinformatics SDK + cookbook for one-line comparative-genomics
analyses on a single workstation with local Docker.  Each tool runs in
its own container (no native installs), each recipe is one CLI call,
and a privacy-first LLM companion is available when you want it.

---

## What you get

- **20 cookbook recipes** invokable as one-liners:
  - *Comparative genomics (8)*: pangenome, ANI, phylogeny, GWAS,
    gene-family evolution, AMR/VF catalogue, COG enrichment, NCBI
    download.
  - *Per-pipeline (12)*: prokaryote_assembly, eukaryote_assembly,
    rnaseq_deg, metagenomics_profile, metagenome_assembly, scrna_seq,
    chip_seq, atac_seq, methylation_wgbs, proteomics_dda,
    germline_variants, joint_genotyping (GATK cohort best practice).
- **110 tools** registered across 16 categories, all pulled as
  BioContainer images at run time — nothing to install on the host
  beyond Docker + Python.
- **Hardware-aware**: every tool is classified `installable` /
  `runnable_slow` / `incompatible` against your CPU / RAM / GPU / arch.
- **Input-hash caching**: re-running a recipe with unchanged inputs
  returns in seconds.
- **Run provenance**: every recipe writes `provenance.json` +
  `ro-crate-metadata.json` recording input SHA-256, container image
  digests, commands, and timestamps — a self-describing research object
  for reproducibility and journal submission.  `--no-provenance` to skip.
- **Privacy-first LLM companion** (optional): terminology Q&A, sanitized
  error diagnosis, tool-registration assist.  Disabled by default.

---

## Install

**From a git checkout (for development / editing recipes):**

```bash
git clone https://github.com/hope9901/bioflow
cd bioflow
pip install -e .

# Verify host (Docker, RAM, disk, registry, …) in one command
bioflow doctor
```

**As a package (the tool registry is bundled into the wheel):**

```bash
pip install bioflowkit        # PyPI distribution name (from 0.2.0)
bioflow doctor                # CLI + Python import stay `bioflow`
bioflow recipe list           # works from any directory
```

> Why the two names? The PyPI namespace `bioflow` was taken in 2018.
> Everything else — `from bioflow import stage`, `bioflow` CLI,
> `https://github.com/hope9901/bioflow` — is unchanged.

**As a container (no Python setup needed):**

```bash
docker build -f docker/core/Dockerfile -t bioflow .
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":/workspace -v /refs:/refs \
  bioflow recipe run prokaryote_assembly --r1 ... --r2 ... --out /workspace/out
```

The orchestrator mounts the host Docker socket and launches each tool as
a *sibling* container (not Docker-in-Docker).

### Optional one-time setup for the LLM companion

```bash
bioflow setup                       # detects CPU/RAM/GPU, recommends a backend
bioflow setup --backend disabled    # explicit no-LLM mode (default)
bioflow setup --backend anthropic   # cloud (needs ANTHROPIC_API_KEY env)
bioflow setup --backend ollama      # local Ollama instance
```

Writes `~/.bioflow/config.yaml`.  Nothing is sent to any model until you
opt in.  See [LLM companion](#llm-companion) for the safety model.

---

## Quick start — Cookbook recipes

Eight curated end-to-end pipelines.  Run from the CLI; no Python
required.

```bash
bioflow recipe list                          # show every recipe + its DAG
bioflow recipe show pangenome                # render the DAG without running
bioflow recipe run pangenome --taxon Dickeya --max 13 --out ./out
bioflow recipe run pangenome --taxon Pectobacterium --dry-run
```

**Comparative genomics**

| Recipe | One-line description |
|---|---|
| `download_taxon`     | Every RefSeq assembly of a taxon (no Docker) |
| `pangenome`          | NCBI fetch → parallel Prokka → Roary |
| `phylogeny`          | Single-copy core → MAFFT × N → IQ-TREE ML |
| `ani_matrix`         | All-vs-all FastANI |
| `gwas`               | Scoary over a Roary GPA |
| `cafe_evolution`     | CAFE5 gene-family expansion / contraction |
| `amr_vf_catalogue`   | ABRicate × N genomes × M DBs |
| `cog_enrichment`     | DIAMOND vs COG-2024 → per-bucket categories |

**One recipe per pipeline area**

| Recipe | Pipeline | One-line description |
|---|---|---|
| `prokaryote_assembly`   | Genome assembly | fastp → SPAdes → QUAST → Prokka |
| `eukaryote_assembly`    | Genome assembly | NanoPlot → Flye → Medaka → compleasm (long-read) |
| `rnaseq_deg`            | RNA-seq DEG    | fastp → Salmon → DESeq2 (tximport bridge) |
| `metagenomics_profile`  | Metagenomics   | fastp → Kraken2 → Bracken |
| `metagenome_assembly`   | Metagenomics   | fastp → MEGAHIT → minimap2 → MetaBAT2 → CheckM2 |
| `scrna_seq`             | scRNA-seq      | STARsolo → Scanpy (10x, license-free) |
| `chip_seq`              | ChIP-seq       | TrimGalore → Bowtie2 → Picard → MACS3 → HOMER |
| `atac_seq`              | ATAC-seq       | TrimGalore → Bowtie2 → Picard → MACS3 → TOBIAS |
| `methylation_wgbs`      | Bisulfite      | TrimGalore → Bismark → methylKit |
| `proteomics_dda`        | LC-MS/MS       | msconvert → Comet → Percolator (open-source) |
| `germline_variants`     | Variant calling | fastp → BWA → GATK → bcftools → SnpEff |

Recipes use input-hash caching automatically — a second run with the
same inputs returns in seconds.  Failed stages retry with bumped
resources where configured (e.g. CAFE5 → 2× RAM).

---

## Verify your machine

Run this first after install:

```bash
bioflow doctor                              # 12-point host self-check
bioflow doctor --json                       # CI-friendly structured output
```

`doctor` verifies Python, the Docker CLI + daemon, the docker socket
(sibling-container path), CPU / RAM / disk, the registry, and your
config + workspace directories — each failure prints a one-line fix hint
and the command exits non-zero on the first FAIL.

Deeper inspection:

```bash
bioflow hw                                  # CPU / RAM / GPU / disk profile
bioflow tools                               # all tools, grouped by compatibility
bioflow tools --category assembly           # filter by category
bioflow tools --recommend genome_assembly   # ranked preset picks for this host
```

---

## Reference databases

Some pipelines need external databases (Pfam, eggNOG, BUSCO, etc.).
`bioflow` ships a small catalog with a progress-bar downloader.

```bash
bioflow db list                                  # show available DBs
bioflow db fetch busco_bacteria --dest /refs
bioflow db verify busco_bacteria --dest /refs
```

| Key | Size | Used by |
|---|---:|---|
| `busco_bacteria`   | 0.07 GB | busco |
| `busco_insecta`    | 0.08 GB | busco |
| `busco_vertebrata` | 0.30 GB | busco |
| `pfam`             | 0.50 GB | interproscan |
| `dfam_curated`     | 2.00 GB | repeatmasker, earlgrey |
| `uniprot_sprot`    | 0.25 GB | braker3 |
| `eggnog`           | 8.50 GB | eggnog_mapper |

---

## Preset pipelines vs recipes — which do I use?

bioflow ships **two entry points** for the same workflows:

| | Recipe (`bioflow recipe run`) | Preset (`bioflow recommend --preset`) |
|---|---|---|
| **Defined in** | Python (`@stage` + `@pipeline`) | YAML (declarative chain of tool IDs) |
| **Customisation** | Edit Python; full control flow, fan-out, retry | Edit YAML; swap tool IDs |
| **Hardware filter** | Per-stage `cpu`/`ram_gb` declared in `@stage` | Whole-preset score from registry YAMLs |
| **Best for** | Active execution, tuning, custom logic | Picking the recommended chain on this host |

Presets that have a matching recipe are linked via a `recipe:` field —
e.g. `prokaryote_denovo_short.yaml` points to the `prokaryote_assembly`
recipe.  Pick whichever surface fits your workflow.

---

## Preset pipelines (multi-stage YAML path)

For workloads that don't fit the cookbook recipes (single-sample read
QC → assembly → annotation), use the preset pipelines:

```bash
cp examples/config_prokaryote_short.yaml my_config.yaml
# edit my_config.yaml → set r1/r2 paths and workdir

bioflow recommend --preset prokaryote_denovo_short --config my_config.yaml
bioflow recommend --preset prokaryote_denovo_short --config my_config.yaml --dry-run
```

Or build a custom plan interactively:

```bash
bioflow custom --pipeline genome_assembly --out my_plan.yaml
bioflow run my_plan.yaml
```

Available presets:

| Preset | Pipeline | Species | Data type | Mode |
|---|---|---|---|---|
| `prokaryote_denovo_short`        | genome_assembly | prokaryote      | short     | de_novo |
| `prokaryote_denovo_hybrid`       | genome_assembly | prokaryote      | hybrid    | de_novo |
| `eukaryote_denovo_hifi`          | genome_assembly | eukaryote       | long_hifi | de_novo |
| `eukaryote_denovo_hybrid`        | genome_assembly | eukaryote_small | hybrid    | de_novo |
| `eukaryote_resequencing`         | genome_assembly | eukaryote       | short     | resequencing |
| `rnaseq_deseq2_standard`         | rnaseq_deg      | eukaryote       | short     | de_novo |
| `metagenomics_kraken2_standard`  | metagenomics    | any             | short     | profiling |
| `metagenomics_metaphlan4_standard` | metagenomics  | any             | short     | profiling |
| `scrna_seq_10x_seurat`           | scrna_seq       | eukaryote       | short     | de_novo |
| `scrna_seq_10x_scanpy`           | scrna_seq       | any             | short     | de_novo |
| `chip_seq_standard`              | chip_seq        | any             | short     | peak_calling |
| `atac_seq_standard`              | atac_seq        | any             | short     | peak_calling |
| `methylation_bismark_wgbs`       | methylation     | any             | short     | wgbs |
| `proteomics_msfragger_dda`       | proteomics      | any             | ms_dda    | dda |

### Pipeline stages (overview)

| Pipeline | Stages | Example tools |
|---|---|---|
| **Genome Assembly & Annotation** (6) | Read QC · Assembly · Assembly QC · Repeat masking (eukaryote) · Structural annotation · Functional annotation | fastp · SPAdes/hifiasm/Flye · QUAST/BUSCO · RepeatModeler · Prokka/BRAKER · eggNOG-mapper |
| **RNA-seq DEG** (4)            | QC · Alignment/Quant · DEG · Enrichment           | fastp · STAR/Salmon · DESeq2 · clusterProfiler |
| **Metagenomics** (5)           | QC · Host removal · Taxonomic · Functional · Diff-abundance | fastp · KneadData · Kraken2/MetaPhlAn4 · HUMAnN3 · LEfSe |
| **scRNA-seq** (5)              | Demux/Align · QC · Cluster · Marker · Trajectory  | Cell Ranger · Scanpy/Seurat · Monocle3 |
| **ChIP-seq / ATAC-seq** (5)    | QC · Align · Peak call · Annotation/Coverage · Motif | TrimGalore · Bowtie2 · MACS3 · HOMER/deepTools · TOBIAS |
| **Bisulfite Methylation** (4)  | QC · Bisulfite align · Extract · DMR              | TrimGalore · Bismark · MethylKit |
| **LC-MS/MS Proteomics** (5)    | Convert · Search · FDR · Quant · Stats            | msconvert · MSFragger · Percolator · FragPipe/MaxQuant |

---

## LLM companion

bioflow ships a thin LLM helper that **never** runs as part of the
critical execution path — it only proposes text the user reviews.

| Capability | Data sent to model | Default |
|---|---|---|
| `bioflow llm explain "<term>"`                        | the term + 1 category word | safe; runs once a backend is configured |
| `bioflow llm diagnose --stage … --command … --stderr …` | command + last 2 KB of stderr, **redacted** | opt-in |
| `bioflow llm new-tool --tool prokka --help-file h.txt`  | tool name + its public `--help` output | opt-in |
| `bioflow llm suggest --tool prokka --intent "..."`      | tool name + user-typed intent | opt-in |
| `bioflow llm redact` (stdin → stdout)                   | nothing — local-only utility | always works |
| `bioflow llm audit`                                     | nothing — reads local log    | always works |

**Backends**: `disabled` (default) · `ollama` (local) · `anthropic`
(cloud) · `openai` (cloud).

**Auto-redaction** before every diagnose call replaces:
`C:\Users\*` / `/Users/*` / `/home/*` → `<USER>`, workspace path →
`<WORKSPACE>`, emails → `<EMAIL>`, IPv4 → `<IP>`, 40+ char tokens →
`<TOKEN>`, plus any custom regex you supply.

**Daily cost cap** (cloud backends only): set `daily_cost_cap_usd` in
`~/.bioflow/config.yaml` (or `BIOFLOW_LLM_DAILY_CAP_USD` env var).  Any
call whose pre-estimate would push the day's cumulative spend above the
cap is refused — no token is sent.  Inspect today's usage with
`bioflow llm audit`.

**Resolution order** for every LLM knob:
explicit argument → env var → `~/.bioflow/config.yaml` → `disabled`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  CLI  recipe / recommend / custom / run / db / setup / llm  │
└──────────────────────┬──────────────────────────────────┘
                       │
       ┌───────────────▼──────────────────────┐
       │   Python SDK + Orchestrator          │
       │  @stage · @pipeline · cache · retry  │
       │  Hardware filter · Report builder    │
       └──────┬──────────────────┬────────────┘
              │                  │
   ┌──────────▼──────┐  ┌────────▼────────────────┐
   │  Tool Registry  │  │  Docker Engine          │
   │  58 YAML tools  │  │  Sibling-container ptn  │
   │  in 15 categories│  │  Live log streaming    │
   └─────────────────┘  └─────────────────────────┘
```

`bioflow` is never a daemon.  Every command spins up briefly, does its
work, and exits.

---

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/unit -q       # 426 unit tests
python -m pytest tests/integration/  # requires Docker daemon
```

### Project layout

```
bioflow/
  cli.py              CLI: hw · tools · recommend · custom · run · db · ncbi · update · recipe · setup · llm
  sdk.py              @stage / @pipeline / parallel='auto' / cache / retry
  report.py           HTML report accumulator (Report.add_section / add_figure / …)
  io.py               CRLF-safe text, atomic write, HTTP download with retry
  recipes/            8 cookbook pipelines (auto-registered)
  llm/                Opt-in LLM companion (explain / diagnose / new-tool / suggest / audit)
  core/               Hardware profiler · registry loader · runner · planner · checkpoint · NCBI

registry/
  schema.yaml         JSON Schema for tool YAMLs
  tools/              58 tools in 15 categories (qc, assembly, alignment, comparative_genomics, …)
  presets/            14 curated preset YAMLs

examples/             config_*.yaml for each pipeline + *_demo.py for the SDK
data/test/            Synthetic fixtures (ecoli_small, rnaseq_toy)
docker/               core/Dockerfile + docker-compose.yml (sibling-container)
docs/MAINTAINER.md    Scheduled-update workflow (read this only if you own the GitHub repo)
```

---

## License

MIT
