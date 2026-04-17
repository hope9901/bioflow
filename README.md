# bioflow

[![tests](https://img.shields.io/badge/tests-86%20passed-brightgreen)](tests/)
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
| **Hardware checks** | CPU / RAM / GPU / disk / arch → installable / runnable_slow / incompatible |
| **Preset recommendation** | `bioflow tools --recommend` scores all presets against your hardware |
| **Artifact chaining** | Planner auto-fills inter-stage file paths at plan time |
| **Checkpoint / resume** | `.bioflow_state.json` — completed stages skipped on re-run |
| **Progress bar** | Rich per-stage spinner + elapsed time during `bioflow run` |
| **Live log streaming** | DockerBackend streams container stdout/stderr in real time |
| **Failure report** | Failed stages shown in red with error detail in HTML summary |
| **Reports** | MultiQC aggregation + HTML pipeline summary |
| **Reference DB management** | `bioflow db fetch/list/verify` — 7 catalog entries with progress bar |
| **Monthly updates** | Deep Research → smoke-test → manual approval → registry PR |

---

## Quick start

### 1. Prerequisites

```bash
# Docker ≥ 20.10 and Python ≥ 3.9
docker info            # verify Docker is running
pip install -e .       # installs bioflow + all deps
```

### 2. Inspect this machine

```bash
bioflow hw                                  # CPU / RAM / GPU / disk profile
bioflow tools                               # all tools, grouped by hw-compatibility
bioflow tools --category assembly           # filter by category
bioflow tools --recommend genome_assembly   # ranked preset suggestions for this hw
```

### 3. Fetch reference databases

```bash
bioflow db list                             # show all available DBs
bioflow db fetch busco_bacteria --dest /refs
bioflow db fetch eggnog          --dest /refs
bioflow db verify busco_bacteria --dest /refs
```

### 4. Run a preset pipeline

```bash
# Copy and edit an example config
cp examples/config_prokaryote_short.yaml my_config.yaml
# edit my_config.yaml → set r1/r2 paths and workdir

bioflow recommend --preset prokaryote_denovo_short --config my_config.yaml

# Preview the plan without executing
bioflow recommend --preset prokaryote_denovo_short --config my_config.yaml --dry-run
```

Example configs are in `examples/`:

| File | Preset |
|---|---|
| `config_prokaryote_short.yaml` | prokaryote_denovo_short |
| `config_eukaryote_hifi.yaml`   | eukaryote_denovo_hifi |
| `config_rnaseq.yaml`           | rnaseq_deseq2_standard |

### 5. Custom interactive pipeline

```bash
bioflow custom --pipeline genome_assembly --out my_plan.yaml
# → questionary prompts for species, read type, mode, then per-stage tool selection
# → only hardware-compatible tools are shown; incompatible/slow ones are labelled

bioflow run my_plan.yaml      # execute the saved plan
```

### 6. Docker (production)

```bash
docker compose -f docker/docker-compose.yml build

# Run with your data mounted
docker compose run --rm -v /path/to/data:/workspace bioflow recommend \
    --preset prokaryote_denovo_short \
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
| `prokaryote_denovo_short`   | genome_assembly | prokaryote     | short    | de_novo |
| `prokaryote_denovo_hybrid`  | genome_assembly | prokaryote     | hybrid   | de_novo |
| `eukaryote_denovo_hifi`     | genome_assembly | eukaryote      | long_hifi | de_novo |
| `eukaryote_denovo_hybrid`   | genome_assembly | eukaryote_small | hybrid  | de_novo |
| `eukaryote_resequencing`    | genome_assembly | eukaryote      | short    | resequencing |
| `rnaseq_deseq2_standard`    | rnaseq_deg      | eukaryote      | short    | de_novo |

---

## Reference databases

`bioflow db list` shows all catalog entries.

| Key | Description | Size | Used by |
|---|---|---|---|
| `busco_bacteria` | BUSCO bacteria_odb10 | 0.07 GB | busco |
| `busco_insecta` | BUSCO insecta_odb10 | 0.08 GB | busco |
| `busco_vertebrata` | BUSCO vertebrata_odb10 | 0.3 GB | busco |
| `pfam` | Pfam-A 36.0 HMMs | 0.5 GB | interproscan |
| `dfam_curated` | Dfam 3.8 curated repeats | 2.0 GB | repeatmasker, earlgrey |
| `uniprot_sprot` | UniProt Swiss-Prot | 0.25 GB | braker3 |
| `eggnog` | eggNOG v5.0 | 8.5 GB | eggnog_mapper |

---

## Project layout

```
bioflow/                 Python orchestrator package
  cli.py                 Typer CLI: hw / tools / recommend / custom / run / db / update
  core/
    hardware.py          CPU/RAM/GPU/disk/arch detection (psutil + pynvml)
    registry.py          Tool YAML loader + Pydantic models
    compatibility.py     hw ↔ tool matching + recommend_presets()
    planner.py           Preset loading, artifact chaining, interactive_build()
    runner.py            Docker sibling-container executor + Rich progress bar
    dag.py               Topological stage sort (Kahn's algorithm)
    checkpoint.py        .bioflow_state.json — resume + failure tracking
    logger.py            Structured JSON logging
    report.py            MultiQC + HTML pipeline summary with failure highlights
    db.py                Reference DB catalog, fetch (with progress), verify

registry/
  schema.yaml            JSON Schema (Draft 2020-12) for tool validation
  tools/<category>/      29 tool YAML files
  presets/               6 curated preset YAML files

docker/
  core/Dockerfile        python:3.12-slim + Docker CLI + bioflow
  docker-compose.yml     mounts host Docker socket (sibling-container)

examples/
  config_prokaryote_short.yaml   prokaryote de-novo short config
  config_eukaryote_hifi.yaml     eukaryote HiFi de-novo config
  config_rnaseq.yaml             RNA-seq DEG config

data/
  test/ecoli_small/      Synthetic prokaryote test fixtures (FASTQ + reference)
  test/rnaseq_toy/       Synthetic RNA-seq test fixtures
  references/            Mount point for external DBs (not bundled)

update/
  research_prompt.md     Standard monthly Deep Research prompt
  benchmark.py           Candidate smoke-test CLI (--real for live Docker)
  candidates/YYYY-MM/    Draft tool YAMLs from Deep Research run
  CHANGELOG.md           Registry version history

tests/
  unit/                  63 unit tests
  e2e/                   9 end-to-end tests (MockBackend, no Docker)
  integration/           5 integration tests (require Docker, --real flag)
```

---

## Monthly registry update workflow

1. Run the Deep Research prompt in `update/research_prompt.md` — targets the last 60 days of literature.
2. Save candidate tool YAMLs to `update/candidates/YYYY-MM/`.
3. Run smoke tests:
   ```bash
   python update/benchmark.py --all-candidates update/candidates/2026-05/
   python update/benchmark.py --all-candidates update/candidates/2026-05/ --real  # with Docker
   ```
4. **Manually review** passing candidates, then move to `registry/tools/`.
5. `update/CHANGELOG.md` is auto-appended with `--append-changelog`.

---

## Development

```bash
pip install -e ".[dev]"                    # installs test + lint deps
python -m pytest tests/unit tests/e2e -v  # 86 passed
python -m pytest tests/integration/ -v    # requires Docker daemon
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  CLI  (bioflow recommend / custom / run / db / …)       │
└──────────────────────┬──────────────────────────────────┘
                       │
       ┌───────────────▼──────────────────────┐
       │   Python Orchestrator (core)         │
       │  Planner → DAG → Runner              │
       │  Checkpoint · Logger · Report · DB   │
       └──────┬──────────────────┬────────────┘
              │                  │
   ┌──────────▼──────┐  ┌────────▼────────────────┐
   │  Tool Registry  │  │  Docker Engine           │
   │  (YAML files)   │  │  per-tool container      │
   │  29 tools       │  │  sibling-container ptn   │
   └─────────────────┘  │  live log streaming      │
                        └─────────────────────────-┘
              ▲
              │ monthly PR (semi-automated)
   ┌──────────┴───────────────────────┐
   │  Deep Research → benchmark.py   │
   │  → manual review → registry PR  │
   └──────────────────────────────────┘
```

---

## License

MIT
