# bioflow

[![tests](https://img.shields.io/badge/tests-63%20passed-brightgreen)](tests/)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Bioinformatics pipeline platform — genome assembly/annotation and RNA-seq DEG —
orchestrated from Python over per-tool Docker containers (sibling-container pattern).

---

## Features

| | |
|---|---|
| **Two pipelines** | Genome Assembly & Annotation (6 stages) · RNA-seq DEG (4 stages) |
| **Two modes** | `recommend` (fixed curated preset) · `custom` (interactive, hardware-filtered) |
| **Read types** | Illumina short · PacBio HiFi · ONT long · hybrid |
| **Species** | Prokaryote · Eukaryote · Eukaryote (small genome) |
| **29 tools registered** | QC, assembly, annotation, DEG, enrichment — BioContainers images |
| **Hardware checks** | CPU / RAM / GPU / disk / arch tested before presenting tool choices |
| **Artifact chaining** | Planner auto-fills inter-stage file paths at plan time |
| **Checkpoint / resume** | `.bioflow_state.json` — completed stages skipped on re-run |
| **Reports** | MultiQC aggregation + HTML pipeline summary (stdlib, no extra deps) |
| **Monthly updates** | Semi-automated Deep Research workflow → smoke-test → manual approval |

---

## Quick start

### 1. Prerequisites

```bash
# Docker ≥ 20.10 and Python ≥ 3.9
docker info            # verify Docker is running
pip install bioflow    # or: pip install -e .
```

### 2. Inspect this machine

```bash
bioflow hw             # CPU / RAM / GPU / disk profile
bioflow tools          # all tools, grouped by hw-compatibility
bioflow tools --category assembly   # filter by category
```

### 3. Run a preset pipeline

Create a config file (see `examples/config_recommend.yaml`):

```yaml
pipeline:  genome_assembly
species:   prokaryote
read_type: short
mode:      de_novo
inputs:
  sample_id: ecoli_test
  r1: /workspace/in/R1.fastq.gz
  r2: /workspace/in/R2.fastq.gz
workdir:      /workspace/out
registry_dir: registry
```

Then run:

```bash
bioflow recommend --preset prokaryote_denovo_short --config config.yaml

# Preview the plan without running
bioflow recommend --preset prokaryote_denovo_short --config config.yaml --dry-run
```

### 4. Custom interactive pipeline

```bash
bioflow custom --pipeline genome_assembly --out my_plan.yaml
# Follow the prompts — only hw-compatible tools are shown
bioflow run my_plan.yaml
```

### 5. Docker (production)

```bash
docker compose -f docker/docker-compose.yml build
docker compose run --rm bioflow recommend \
    --preset eukaryote_denovo_hifi \
    --config /workspace/config.yaml
```

---

## Pipelines

### Genome Assembly & Annotation (6 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | Read QC | fastp · filtlong · nanoplot |
| step2 | Assembly | SPAdes · hifiasm · Flye · Unicycler · BWA-MEM2 |
| step3 | Assembly QC | QUAST · BUSCO · CheckM2 · Merqury |
| step4 | Repeat masking *(eukaryote only)* | Earl Grey · RepeatModeler · RepeatMasker |
| step5 | Structural annotation | BRAKER3 · Prokka · Bakta |
| step6 | Functional annotation | eggNOG-mapper · InterProScan |

### RNA-seq DEG (4 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | QC | fastp |
| step2 | Alignment / quant | HISAT2 · STAR · Salmon · Kallisto |
| step3 | DEG | DESeq2 · edgeR · limma-voom |
| step4 | Enrichment | clusterProfiler · topGO · GSEA |

---

## Available presets

| Preset | Pipeline | Species | Read type | Mode |
|---|---|---|---|---|
| `prokaryote_denovo_short` | genome_assembly | prokaryote | short | de_novo |
| `prokaryote_denovo_hybrid` | genome_assembly | prokaryote | hybrid | de_novo |
| `eukaryote_denovo_hifi` | genome_assembly | eukaryote | long_hifi | de_novo |
| `eukaryote_denovo_hybrid` | genome_assembly | eukaryote_small | hybrid | de_novo |
| `eukaryote_resequencing` | genome_assembly | eukaryote | short | resequencing |
| `rnaseq_deseq2_standard` | rnaseq_deg | eukaryote | short | de_novo |

---

## Project layout

```
bioflow/                 Python orchestrator package
  cli.py                 Typer CLI (hw / tools / recommend / custom / run / db / update)
  core/
    hardware.py          CPU/RAM/GPU/disk/arch detection (psutil + pynvml)
    registry.py          Tool YAML loader + Pydantic models
    compatibility.py     hw ↔ tool matching (installable / runnable_slow / incompatible)
    planner.py           Preset loading, artifact chaining, interactive_build()
    runner.py            Docker sibling-container executor (MockBackend + DockerBackend)
    dag.py               Topological stage sort (Kahn's algorithm)
    checkpoint.py        .bioflow_state.json — resume support
    logger.py            Structured JSON logging
    report.py            MultiQC + HTML pipeline summary

registry/
  schema.yaml            JSON Schema (Draft 2020-12) for tool validation
  tools/<category>/      29 tool YAML files
  presets/               6 curated preset YAML files

docker/
  core/Dockerfile        python:3.12-slim + Docker CLI + bioflow
  docker-compose.yml     mounts host Docker socket (sibling-container)

data/
  test/ecoli_small/      Synthetic prokaryote test fixtures
  test/rnaseq_toy/       Synthetic RNA-seq test fixtures
  references/            Mount point for external DBs (not bundled)

update/
  research_prompt.md     Standard monthly Deep Research prompt
  benchmark.py           Candidate smoke-test CLI
  candidates/YYYY-MM/    Draft tool YAMLs from Deep Research run
  CHANGELOG.md           Registry version history

tests/
  unit/                  54 unit tests
  e2e/                   9 end-to-end tests (MockBackend)
```

---

## Monthly registry update workflow

1. Run the Deep Research prompt in `update/research_prompt.md` — targets the last 60 days of literature.
2. Save candidate tool YAMLs to `update/candidates/YYYY-MM/`.
3. Run smoke tests:
   ```bash
   python update/benchmark.py --all-candidates update/candidates/2026-05/
   # --real flag to use actual Docker for container-pull verification
   ```
4. **Manually review** passing candidates, then move to `registry/tools/`.
5. `update/CHANGELOG.md` is auto-appended with `--append-changelog`.

---

## Development

```bash
pip install -e ".[dev]"              # installs test + lint deps
python -m pytest tests/ -v           # 63 passed, 1 skipped
python -m pytest tests/unit/ -q      # unit only
python -m pytest tests/e2e/  -q      # e2e only (MockBackend, no Docker)
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  CLI  (bioflow recommend / custom / run / …)    │
└──────────────────────┬──────────────────────────┘
                       │
       ┌───────────────▼──────────────────┐
       │   Python Orchestrator (core)     │
       │  Planner → DAG → Runner          │
       │  Checkpoint · Logger · Report    │
       └──────┬────────────────┬──────────┘
              │                │
   ┌──────────▼──────┐  ┌──────▼──────────────┐
   │  Tool Registry  │  │  Docker Engine       │
   │  (YAML files)   │  │  per-tool container  │
   │  29 tools       │  │  (sibling pattern)   │
   └─────────────────┘  └──────────────────────┘
              ▲
              │ monthly PR
   ┌──────────┴───────────────┐
   │  Deep Research + smoke   │
   │  test → manual approval  │
   └──────────────────────────┘
```

---

## License

MIT
