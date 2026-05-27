# Changelog

> This file tracks **software releases**.
> For the monthly tool-registry update log see
> [`update/REGISTRY_CHANGELOG.md`](update/REGISTRY_CHANGELOG.md).

---

## [0.1.11] — 2026-05-15

### Added — 30 tools across 11 pipeline categories (76 → 106)

Filling the largest gaps so every pipeline can be assembled from the
registry without inventing inline images.  Headline fix: a recipe
no longer needs to inline `quay.io/biocontainers/multiqc:…` or
`bedtools:…` — these are now real registry entries that
`bioflow tools` lists and `bioflow update auto` tracks.

**QC (3):** multiqc · cutadapt · seqkit
**Alignment (3):** minimap2 · bwa · bedtools
**Assembly QC (2):** compleasm · gfastats
**Struct. annotation (2):** augustus · liftoff
**Functional annotation (3):** antismash · gtdbtk · dbcan
**RNA-seq align/quant (3):** subread (featureCounts) · stringtie · rsem
**Enrichment (3):** gseapy · topgo · enrichr
**scRNA-seq (3):** bustools · scrublet · harmony
**Metagenomics (2):** metabat2 · maxbin2
**Epigenomics (1):** methylpy
**Comparative genomics (3):** panaroo · mash · skani
**Proteomics (2):** openms · xtandem

### Verified
- T1 freshness ran against all 30 → **30/30 image references resolve**
  (initial `xtandem` had wrong BioContainers package name; corrected
  to `xtandem` not `tandem`).
- Every tool with an active GitHub repo declares `source_repo:` so T2
  weekly release-watch covers them automatically.

### Fixed
- `days_since_last_candidate` / `days_since_last_t3_run` clamp to 0
  when filesystem clock skew yields a sub-second-in-the-future mtime
  on Windows.

### Bumps
- Tool count: 76 → 106
- Version: 0.1.10 → 0.1.11

---

## [0.1.10] — 2026-05-15

### Added — 12 genome assembly tools (64 → 76 registered)

Filling out the assembly category beyond the original 4 (SPAdes,
hifiasm, Flye, Unicycler):

**Long-read assemblers (4):**
- `canu`        — classic long-read assembler with `-pacbio-hifi`
- `verkko`      — T2T-quality HiFi + ONT hybrid (Rautiainen 2023)
- `nextdenovo`  — popular ONT/PacBio assembler (Hu 2024)
- `shasta`      — fast ONT assembler (Shafin 2020)

**Other assemblers (4):**
- `raven`       — fast ONT alternative to Flye (Vaser & Sikic 2021)
- `masurca`     — heavy-duty hybrid for large genomes (Zimin 2017)
- `megahit`     — short-read genome / metagenome (Li 2015)
- `abyss`       — short-read large-genome assembler (Jackman 2017)

**Polishing (4):**
- `pilon`       — short-read polish (Walker 2014)
- `racon`       — long-read polish (Vaser 2017)
- `medaka`      — ONT-specific polish (Oxford Nanopore)
- `nextpolish`  — fast polisher (Hu 2020)

All 12 verified pullable via `update/freshness_check.py` against
quay.io / Docker Hub — no yanked images.  Each declares
`source_repo:` so T2 weekly release-watch covers them automatically.

### Bumps
- Tool count: 64 → 76
- Version: 0.1.9 → 0.1.10

---

## [0.1.9] — 2026-05-15

### Fixed — critical
- `proteomics_dda` was unrunnable: `fcyu/fragpipe:22.0` and
  `fcyu/msfragger:4.1` are not public Docker images.  Recipe
  rewritten on top of an open-source stack (msconvert → Comet →
  Percolator), all images pullable from BioContainers / chambm.
- `bioflow.DockerBackend` was not re-exported from `bioflow.__init__`;
  added so users can switch from MockBackend to the real backend
  with `from bioflow import DockerBackend`.

### Added — first real-Docker integration tests
- `tests/integration/test_sdk_real_docker.py` — 5 tests that pull
  `alpine:3.19` and exercise the full SDK contract: single-stage
  exec, two-stage chaining, failure propagation, external-input
  auto-mount (BLOCKER 2), cache hit on repeat call.
- Auto-skipped when no Docker daemon — explicitly opt-in via
  `pytest tests/integration/ -m docker -v`.
- First time the SDK has been validated against a real Docker
  daemon (previously: MockBackend only).

### Added — schema fields
- Optional `pin_reason: string` — explains why a tool is
  intentionally not bumped to the latest upstream.
- Optional `deprecated: boolean` + `deprecation_note: string` +
  `replaced_by: string` — marks a tool YAML as deprecated without
  deleting the file (preserves reproducibility / rollback).
- Used by the new `comet.yaml` to replace the deprecated
  `msfragger.yaml` / `fragpipe.yaml` (no public Docker image).

### Added — T3 cron silence detection in T1
- `update/freshness_check.py` now reports both:
  - Days since the last Cowork candidate landed
    (`update/candidates/<YYYY-MM>/*.yaml` newest mtime)
  - Days since the last `bioflow update auto` run
    (`update/last_run.json` mtime)
- Maintainer is warned within 24 hours if either scheduler stops.

### Added — registry policy
- `update/REGISTRY_CHANGELOG.md` — first manual review entry
  documenting the 2 yanked images, 27 newer tags noted but pinned
  for stability, and the new `pin_reason` field for explicit pins.

### Added — type-checking visibility
- CI gained a non-blocking `mypy` advisory job; current error count
  (~36) does not block merging but is visible in PR checks.

### Tests
- 508 → 510 unit tests (+2 T3-silence detection).
- New integration suite: 5 tests passing against real Docker.

### Bumps
- Version: 0.1.8 → 0.1.9.

---

## [0.1.8] — 2026-05-15

### Added — multi-cadence registry update model
Five complementary cadences keep `registry/tools/` from silently rotting.
Previously: one monthly cadence (Cowork Deep Research → local cron).
Now:

- **T1 daily — `update/freshness_check.py`** + `scripts/install-schedule-daily.{ps1,sh}`
  - Queries quay.io + Docker Hub REST APIs for every registered image
  - Surfaces newer tags, yanked images, "tag aged out", and Cowork
    silence (>35 days since last candidate)
  - Writes `update/notifications/freshness-<DATE>.md`; exit code
    0=clean / 1=updates available / 2=yanked
  - First real run on the current registry: 27 newer-tag candidates,
    2 yanked images (`fcyu/fragpipe`, `fcyu/msfragger` — never on
    Docker Hub), 32 tags aged out
- **T2 weekly — `update/release_watch.py`** + `scripts/install-schedule-weekly.{ps1,sh}`
  - Polls GitHub releases for every tool that declares
    `source_repo: <owner>/<repo>` in its YAML
  - Files a candidate YAML draft under `update/candidates/<YYYY-MM>/`
    when upstream is newer (state-tracked in
    `update/release_watch_state.json` so the same release is never
    re-filed)
  - Honours `GITHUB_TOKEN` env var for rate-limit (60/hr → 5000/hr)
  - 8 representative tools seeded with `source_repo` for the watcher
- **T3 monthly** *(unchanged)* — existing `bioflow update auto` cron
- **T4 quarterly — `docs/maintainer/quarterly_audit_prompt.md`**
  - Cowork-side prompt for deprecation review (last commit,
    citation trend, successor-fork detection)
- **T5 event-driven — `.github/workflows/candidate-smoke-test.yml`**
  - On any PR touching `update/candidates/**`, runs
    `bioflow update auto` on only the changed dirs and comments a
    per-candidate ✅/❌ summary on the PR

### Added — schema
- Optional `source_repo:` field (regex `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
  enables the T2 release-watch for that tool.

### Added — docs
- `docs/maintainer/UPDATE_CADENCES.md` — 5-tier model with cron
  examples, exit-code semantics, and a matrix of which cadence
  catches which failure mode.
- `docs/MAINTAINER.md` now links to it from its first paragraph.

### Tests
- 476 → 508 unit tests (+32):
  - `test_freshness_check.py` (15 tests): image-string parsing for
    quay/Docker Hub variants, version comparison with build suffix,
    HTTPError yanked/check_failed branches, report rendering,
    Cowork-pulse detection, CLI exit codes.
  - `test_release_watch.py` (17 tests): `is_newer` ordering,
    candidate generation, state-file dedup, dry-run, no-releases /
    missing source_repo paths, image-tag bump helper.

### Bumps
- Version: 0.1.7 → 0.1.8

---

## [0.1.7] — 2026-05-15

### Fixed — drift from original design (TIER 1)
- `methylation_wgbs` recipe now uses the same Bioconductor image
  (`bioconductor/bioconductor_full:RELEASE_3_18`) registered for the
  `methylkit` tool YAML — the previous `_docker` tag was unverified
  on Docker Hub.
- 3 tools (`scoary`, `diamond`, `mafft`) used by the comparative-
  genomics recipes had no registry YAML.  Added — they now show up in
  `bioflow tools`, get hardware-classified, and can be picked up by
  `bioflow update auto`.
- `samtools.yaml` and `picard.yaml` stage IDs were aspirational.
  samtools is now declared under `utility.bam_processing` (it's
  bundled inline within several aligner BioContainers).  picard dropped
  its `methylation.step2` claim (Bismark has its own
  `deduplicate_bismark`).

### Changed — structural alignment (TIER 2)
- Every preset YAML that has a recipe equivalent now carries a
  ``recipe:`` field linking the two (8 presets total).  Researchers
  can still pick either entry point, but the relationship is now
  declared in the metadata.
- Added the 6 missing pipeline modules
  (`bioflow/pipelines/{chip_seq,atac_seq,metagenomics,scrna_seq,
  methylation,proteomics}.py`) so every preset's `pipeline:` value
  points to a real canonical-stage-IDs module — not just the 2 that
  existed before.
- `bioflow.core.db._DB_CATALOG` gained the 3 reference DBs the new
  recipes actually need: `kraken2_standard_8gb`,
  `10x_whitelist_v3`, `bowtie2_grch38_noalt`.  `bioflow db fetch`
  can now provision them.

### Added — UX (TIER 3)
- `examples/recipes_quickstart.py` — programmatic call signatures for
  all 8 per-pipeline recipes (the missing Python counterpart to the
  CLI `bioflow recipe run` examples in the README).
- README: new "Preset pipelines vs recipes — which do I use?" section
  explaining the two entry points and how they map.

### Tests
- 474 → 476 unit tests (+2 alignment checks):
  - `test_recipe_registry_alignment.py`: asserts every recipe's
    `@stage(image=...)` is registered in `registry/tools/`.
  - `test_pipeline_modules_present`: asserts every preset's
    `pipeline:` value has a matching `bioflow/pipelines/<id>.py`.
- Tool count: 60 → 63 (scoary, diamond, mafft).
- DB catalog: 7 → 10.

---

## [0.1.6] — 2026-05-15

### Fixed
- **CRITICAL: `rnaseq_deg` was unrunnable.**  Two multi-arg stages were
  fanned out with `.map()` (which forwards the whole tuple as the first
  positional arg) instead of `.starmap()` (which unpacks).  This was
  invisible to registration-style tests; only the new e2e suite caught
  it.
- `proteomics_dda`: now actually uses the `fasta_db` argument
  (`fragpipe --database-path …`) and writes the FragPipe manifest via a
  readable `for f in *.mzML; do printf …; done` bash loop instead of a
  triply-escaped inline `awk`.
- `chip_seq` / `atac_seq` / `methylation_wgbs`: replaced the bare
  `*_val_1.fq.gz` glob fed straight to the aligner with `R1=$(ls … |
  head -1)` so multiple matches no longer break `bowtie2 -1` / `bismark
  -1`.
- `scrna_seq`: set explicit `--soloCellFilter EmptyDrops_CR
  --soloFeatures Gene` so the `filtered/` matrix is reproducibly
  produced, and added a `filtered → raw` fall-back so shallow runs still
  yield an h5ad.
- `scrna_seq`: rewrote the inline `python -c` analysis as a sibling
  `analyze.py` (quoting hygiene + independently re-runnable for
  debugging).
- `prokaryote_assembly`: QUAST + Prokka stages now fall back to
  `contigs.fasta` when SPAdes does not produce `scaffolds.fasta`
  (fragmented assemblies).
- `prokaryote_assembly` returns the final `annotate` `StageResult`
  instead of a `dict`, so `bioflow recipe run … --out X` no longer
  prints `result.out_dir = ?`.

### Tests
- 464 → **474** unit tests (+10: `test_recipes_per_pipeline_e2e.py`
  exercises every per-pipeline recipe through MockBackend and asserts
  external inputs are bind-mounted + path-translated).

---

## [0.1.5] — 2026-05-15

### Fixed
- **BLOCKER: per-pipeline recipes were unrunnable via the CLI.**
  `bioflow recipe run` had a hardcoded option set + `candidate` dict, so
  the 8 per-pipeline recipes could not receive `--r1` / `--sample-sheet`
  / etc.  The recipe command now accepts pass-through `--key value`
  tokens, maps `--sample-id` → `sample_id`, coerces integer values, warns
  on unknown options, and prints an actionable hint listing the exact
  missing parameters.
- **BLOCKER: input files outside the workspace were invisible to
  containers.**  The SDK mounted only the workspace and `_translate_command`
  only rewrote workspace paths, so any external `--r1` / reference / index
  path pointed at something neither mounted nor translated.  The SDK now
  scans stage arguments for external `Path` inputs, bind-mounts their
  parent directory at `/inputs/<n>`, and rewrites the command accordingly
  (files, directories, and index-prefixes all handled).  This also fixes
  the same latent bug in the existing `gwas` recipe.

### Tests
- 444 → **464** unit tests (+20: `test_sdk_external_mounts.py`,
  `test_recipe_cli_args.py`).

---

## [0.1.4] — 2026-05-12

### Added
- **8 new per-pipeline recipes** — at least one recipe per pipeline area:
  `prokaryote_assembly`, `rnaseq_deg`, `metagenomics_profile`, `scrna_seq`,
  `chip_seq`, `atac_seq`, `methylation_wgbs`, `proteomics_dda`.
  Total recipe count: 8 → **16**.
- 2 new tool YAMLs to support the new recipes:
  - `samtools` (alignment) — standalone BAM sort/index.
  - `picard` (epigenomics) — MarkDuplicates for ChIP-seq / ATAC-seq dedup.
  Total registered tools: 58 → **60**.

### Tests
- 426 → **444** unit tests (+18: per-pipeline recipe registration smoke
  tests, DAG-shape parametrised tests, registry-total assertion).

---

## [0.1.3] — 2026-05-11

### Added
- **`bioflow update auto --git-commit / --git-push`** — maintainer-only
  flags that, after auto-approval, stage the updated registry +
  CHANGELOG + last_run.json, commit with a deterministic message, and
  push to the configured remote/branch.  Skips the commit cleanly when
  nothing was staged.  Auth (token / SSH key) is the user's
  responsibility — bioflow never stores credentials.
- `--git-remote` / `--git-branch` overrides (defaults: `origin` and the
  current HEAD).
- `install-schedule-windows.ps1` learns `-GitPush -GitRemote -GitBranch`.
- `install-schedule-cron.sh` learns `--git-push --git-remote=...`.

### Changed
- README "Registry updates" section split into **Role A (maintainer)**
  and **Role B (every other clone)**.  Researchers just `git pull` —
  they should never install the scheduled task with `--git-push`.

### Tests
- 422 → 426 unit (+4: git flags off by default, commit on staged
  changes, push implies commit, commit skipped when nothing staged —
  all with mocked `subprocess.run`).

---

## [0.1.2] — 2026-05-11

### Added
- **`bioflow update auto`** — unattended pipeline that walks
  `update/candidates/`, smoke-tests every YAML, writes a JSON report
  to `update/last_run.json`, and (with `--auto-approve`) promotes
  passing candidates to the registry.  Designed to be wired into an
  OS-level scheduler.
- **`scripts/install-schedule-windows.ps1`** — registers a Windows
  Task Scheduler task firing every 4 weeks at 02:30; `-AutoApprove`
  and `-Real` flags pass through; `-Uninstall` removes the task.
- **`scripts/install-schedule-cron.sh`** — appends a single cron line
  (1st of every month at 02:30) to the invoking user's crontab.
- README section "Monthly Deep-Research update (scheduled)" documents
  the install one-liner and the manual workflow.

### Notes
- bioflow itself stays a *no-daemon* tool (Part 5).  Only the OS
  scheduler is long-running.
- `--auto-approve` is OFF by default — the safe scheduled mode just
  benchmarks and reports; you review the JSON before promoting.

### Tests
- 416 → 422 unit (+6: empty candidates, report emission, default-safe
  flag, unknown-action rejection, both installer scripts present).

---

## [0.1.1] — 2026-05-11

Bug-fix release — registry tool taxonomy corrections caught by a user
review.

### Fixed
- **BWA-MEM2** was filed under `category: assembly`.  It is a short-read
  aligner — recategorised to `alignment`.  The tool stays in
  `genome_assembly.step2` (resequencing-mode "step 2" is
  align-then-`samtools consensus`), but the category now reflects what
  the tool is, not which pipeline slot it fills.  Its `output_types`
  also corrected: `[alignment_bam, consensus_fasta]` instead of the
  misleading `[assembly_fasta]`.
- **Trim Galore** was filed under `category: alignment`.  It's a read
  trimmer (Cutadapt wrapper) — recategorised to `qc`, matching its
  stage entries (`*.step1`).
- **`prokka_comparative`** registry entry removed.  It was a redundant
  copy of `prokka` with `--genus Dickeya` hard-coded — a session-1
  artefact that would have produced wrong results on any other taxon.
  The cookbook recipes already call Prokka through their own `@stage`
  definitions, so this entry was unused and dangerous.

### Added
- `tests/unit/test_registry_sanity.py` — 4 new regression tests that
  encode the taxonomy rules so future PRs can't reintroduce these
  three classes of bug:
    * naming substring → must-be-in-category mapping (catches
      BWA / Bowtie / FastQC / etc. under the wrong category)
    * aligners must not advertise `assembly_fasta` outputs
    * no two registry files share an id
    * no `command_template` hard-codes a genus / species

### Tests
- 412 → 416 unit (+4 sanity), all still pass.

---

## [0.1.0] — 2026-05-11

First public release.  Closes the 14-box roadmap in
[`bioflow_진행현황.md`](bioflow_진행현황.md) with two bonus boxes (setup
wizard + audit/cap) added along the way.

### Highlights

- **Deterministic Python SDK** for ad-hoc comparative genomics on one
  workstation — `@stage` / `@pipeline` / `parallel="auto"` / input-hash
  caching / retry-with-resource-bump / log streaming.
- **8 cookbook recipes** invoked as one-liners from the CLI:
  `download_taxon`, `pangenome`, `phylogeny`, `ani_matrix`, `gwas`,
  `cafe_evolution`, `amr_vf_catalogue`, `cog_enrichment`.
- **First-time `bioflow setup` wizard** detects host CPU / RAM / GPU
  and recommends an LLM backend (Ollama local model, or cloud APIs).
- **Privacy-first LLM companion** — disabled by default, automatic
  redaction of paths/emails/IPs/tokens before any error-diagnosis call,
  daily cost cap with pre-call enforcement, JSONL audit log.

### Verified on real data

- Dickeya genus end-to-end (262 RefSeq assemblies, 6.8 h cold,
  0.0 s cached re-run after Phase 1C)
- **Pectobacterium 12-genome demo (Phase 3 verification milestone)**:
    1. NCBI download                       5.9 s
    2. Pangenome (Prokka × 12 + Roary)    26.3 min  (6 parallel auto)
    3. FastANI 12×12                       1.0 s
    4. ABRicate × 36 runs (3 DBs)          31.7 s, 0 failed
    Total wall clock:                     ~26.5 min   summary.html OK
- 426 unit + integration tests pass

### What's intentionally NOT in scope

This release ships everything in the roadmap and nothing the design doc
forbade: no HPC / SLURM / k8s, no multi-user, no WDL / CWL / Nextflow
compat, no web UI / Tower, no LLM-data exposure, no LLM auto-execution.

### Component overview

| Module | Purpose |
|---|---|
| `bioflow.sdk`     | `@stage`, `@pipeline`, fan-out engine, caching, retry, log streaming |
| `bioflow.recipes` | 8 curated cookbook pipelines |
| `bioflow.report`  | HTML accumulator (`Report.add_section / add_figure / add_table / write`) |
| `bioflow.io`      | CRLF-safe text, atomic write, download retry, URL batching |
| `bioflow.llm`     | Opt-in companion: `explain`, `diagnose_failure`, `new_tool`, `suggest_command`, `redact`, audit/cap |
| `bioflow.core.*`  | Hardware profiler, container backend, registry loader, NCBI ingestion |
| `bioflow.cli`     | `hw / tools / recommend / custom / run / db / ncbi / update / recipe / setup / llm` |

### Install

```bash
git clone https://github.com/<you>/bioflow
cd bioflow
pip install -e .
bioflow setup           # optional — picks an LLM backend for your hardware
bioflow recipe list     # 8 ready-to-run recipes
```
