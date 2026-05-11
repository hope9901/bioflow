# bioflow

[![tests](https://img.shields.io/badge/tests-382%20passed-brightgreen)](tests/)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

Multi-omics bioinformatics pipeline platform — covering genome assembly/annotation,
RNA-seq, metagenomics, single-cell RNA-seq, ChIP-seq, ATAC-seq, bisulfite methylation,
and LC-MS/MS proteomics — orchestrated from Python over per-tool Docker containers
(sibling-container pattern).

---

## Features

| | |
|---|---|
| **8 pipelines** | Genome Assembly · RNA-seq DEG · Metagenomics · scRNA-seq · ChIP-seq · ATAC-seq · Methylation · Proteomics |
| **Two modes** | `recommend` (fixed curated preset) · `custom` (interactive, hardware-filtered) |
| **Read / data types** | Illumina short · PacBio HiFi · ONT long · hybrid · LC-MS/MS DDA/DIA |
| **Species** | Prokaryote · Eukaryote · Eukaryote (small) · Any |
| **53 tools registered** | QC, assembly, annotation, DEG, taxonomic profiling, scRNA, peak calling, methylation, proteomics |
| **Hardware checks** | CPU / RAM / GPU / disk / arch → installable / runnable_slow / incompatible |
| **arm64 aware** | Apple Silicon & Linux ARM: x86_64 tools auto-classified as `runnable_slow` (emulation) |
| **Preset recommendation** | `bioflow tools --recommend` scores all presets against your hardware |
| **Artifact chaining** | Planner auto-fills inter-stage file paths at plan time |
| **Checkpoint / resume** | `.bioflow_state.json` — completed stages skipped on re-run |
| **Progress bar** | Rich per-stage spinner + elapsed time during `bioflow run` |
| **Live log streaming** | DockerBackend streams container stdout/stderr in real time |
| **Failure report** | Failed stages shown in red with error detail in HTML summary |
| **Reports** | MultiQC aggregation + HTML pipeline summary |
| **NCBI downloader** | `bioflow ncbi genome/protein` — direct NCBI Datasets & Entrez download |
| **Reference DB management** | `bioflow db fetch/list/verify` — 7 catalog entries with progress bar |
| **Registry approval** | `bioflow update approve` — validate + promote candidate tool YAMLs |
| **Monthly updates** | Deep Research → smoke-test → manual approval → registry PR |

---

## Quick start

### 1. Prerequisites

```bash
# Docker ≥ 20.10 and Python ≥ 3.9
docker info            # verify Docker is running
pip install -e .       # installs bioflow + all deps
```

### 1b. First-time setup (optional — for the LLM companion)

```bash
bioflow setup                       # detects CPU / RAM / GPU,
                                    # recommends a local Ollama model
                                    # or cloud API based on hardware
bioflow setup --yes                 # non-interactive, accept the recommendation
bioflow setup --backend disabled    # explicit no-LLM mode (default if you skip setup)
bioflow setup --backend anthropic   # use cloud Anthropic (needs ANTHROPIC_API_KEY)
```

The wizard writes `~/.bioflow/config.yaml`.  LLM is OFF by default —
nothing is sent anywhere until you opt in.  See the
[LLM companion](#llm-companion-opt-in-privacy-first) section below for
the safety model.

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

### Metagenomics (5 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | Read QC | fastp |
| step2 | Host removal | KneadData |
| step3 | Taxonomic profiling | Kraken2+Bracken · MetaPhlAn4 |
| step4 | Functional profiling | HUMAnN3 |
| step5 | Differential abundance | LEfSe |

### Single-cell RNA-seq (5 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | Demux / Alignment | Cell Ranger (10x) · STARsolo |
| step2 | QC & Filtering | Seurat · Scanpy |
| step3 | Clustering & Dim. Reduction | Seurat · Scanpy |
| step4 | Marker gene / DEG | Seurat · Scanpy |
| step5 | Trajectory / Pseudotime *(optional)* | Monocle3 |

### ChIP-seq (5 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | QC & Trimming | TrimGalore |
| step2 | Alignment | Bowtie2 |
| step3 | Peak calling | MACS3 |
| step4 | Peak annotation / Coverage | HOMER · deepTools |
| step5 | Motif analysis *(optional)* | HOMER |

### ATAC-seq (5 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | QC & Trimming | TrimGalore |
| step2 | Alignment | Bowtie2 |
| step3 | Peak calling | MACS3 |
| step4 | Coverage & Differential | deepTools |
| step5 | Footprinting & Motif *(optional)* | TOBIAS · HOMER |

### Bisulfite Methylation / WGBS (4 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | QC & Trimming | TrimGalore |
| step2 | Bisulfite Alignment | Bismark |
| step3 | Methylation Extraction | Bismark |
| step4 | DMR Analysis *(optional)* | MethylKit |

### Proteomics LC-MS/MS (5 stages)

| Stage | Content | Example tools |
|---|---|---|
| step1 | Format Conversion | msconvert (ProteoWizard) |
| step2 | Database Search | MSFragger |
| step3 | FDR Control | Percolator |
| step4 | Quantification | FragPipe · MaxQuant |
| step5 | Statistical Analysis *(optional)* | FragPipe built-in |

---

## Available presets

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
  cli.py                 Typer CLI: hw / tools / recommend / custom / run / db / update / ncbi
  core/
    hardware.py          CPU/RAM/GPU/disk/arch detection (psutil + pynvml); arch normalisation
    registry.py          Tool YAML loader + Pydantic models
    compatibility.py     hw ↔ tool matching + arm64 emulation + recommend_presets()
    planner.py           Preset loading, artifact chaining, interactive_build() — 8 pipelines
    runner.py            Docker sibling-container executor + Rich progress bar
    dag.py               Topological stage sort (Kahn's algorithm)
    checkpoint.py        .bioflow_state.json — resume + failure tracking
    logger.py            Structured JSON logging
    report.py            MultiQC + HTML pipeline summary with failure highlights
    db.py                Reference DB catalog, fetch (with progress), verify
    ncbi.py              NCBI Datasets API + Entrez genome/protein download
    approve.py           Registry candidate validation & promotion

registry/
  schema.yaml            JSON Schema (Draft 2020-12) for tool validation
  tools/
    qc/                  fastp · fastqc · filtlong · nanoplot · trimgalore
    assembly/            spades · hifiasm · flye · unicycler · bwa_mem2
    assembly_qc/         quast · busco · checkm2 · merqury
    repeat/              earlgrey · repeatmodeler · repeatmasker
    struct_annot/        braker3 · prokka · bakta
    func_annot/          eggnog_mapper · interproscan · diamond_uniprot
    rnaseq_align/        hisat2 · star · salmon · kallisto
    deg/                 deseq2 · edger · limma_voom
    enrichment/          clusterprofiler · topgo · gsea
    alignment/           bowtie2 · trimgalore          ← NEW
    metagenomics/        kraken2 · bracken · metaphlan4 · humann3 · kneaddata · lefse  ← NEW
    single_cell/         cellranger · starsolo · seurat · scanpy · monocle3  ← NEW
    epigenomics/         macs3 · deeptools · homer · bismark · methylkit · tobias  ← NEW
    proteomics/          msconvert · msfragger · percolator · fragpipe · maxquant  ← NEW
  presets/               14 curated preset YAML files

docker/
  core/Dockerfile        python:3.12-slim + Docker CLI + bioflow
  docker-compose.yml     mounts host Docker socket (Linux/macOS/Windows WSL2)

examples/
  config_prokaryote_short.yaml
  config_eukaryote_hifi.yaml
  config_rnaseq.yaml
  config_metagenomics.yaml    ← NEW
  config_scrna_seq.yaml       ← NEW
  config_chip_seq.yaml        ← NEW
  config_atac_seq.yaml        ← NEW
  config_methylation.yaml     ← NEW
  config_proteomics.yaml      ← NEW

data/
  test/ecoli_small/      Synthetic prokaryote test fixtures
  test/rnaseq_toy/       Synthetic RNA-seq test fixtures
  references/            Mount point for external DBs (not bundled)

update/
  research_prompt.md     Standard monthly Deep Research prompt
  benchmark.py           Candidate smoke-test CLI (--real for live Docker)
  candidates/YYYY-MM/    Draft tool YAMLs from Deep Research run
  CHANGELOG.md           Registry version history

tests/
  unit/                  unit tests (153 passed total)
  e2e/                   end-to-end tests (MockBackend, no Docker)
  integration/           integration tests (require Docker, --real flag)
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

## LLM companion (opt-in, privacy-first)

bioflow ships a thin LLM helper that **never** runs as part of the
critical execution path — it only proposes text the user reviews.

| Capability | Data sent to model | Default |
|---|---|---|
| `bioflow llm explain "<term>"` | the term + 1 category word | safe; runs once you've configured a backend |
| `bioflow llm diagnose --stage ... --command ... --stderr ...` | command + last 2 KB of stderr, **redacted** | opt-in |
| `bioflow llm new-tool --tool prokka --help-file h.txt` | tool name + its public `--help` output | opt-in |
| `bioflow llm suggest --tool prokka --intent "..."` | tool name + user-typed intent string | opt-in |
| `bioflow llm redact` (stdin → stdout) | nothing — local-only utility | always works |

**Backends**: `disabled` (default) · `ollama` (local) · `anthropic` (cloud) · `openai` (cloud).

**Auto-redaction** before every diagnose call replaces:
- `C:\Users\*`, `/Users/*`, `/home/*` → `<USER>`
- the bioflow workspace path → `<WORKSPACE>`
- emails → `<EMAIL>`, IPv4 → `<IP>`, 40+ char tokens → `<TOKEN>`
- any custom regex you provide for project-specific PHI

**Resolution order** for `BIOFLOW_LLM_*` knobs:
explicit function argument → env var → `~/.bioflow/config.yaml` → `disabled`.

## License

MIT
