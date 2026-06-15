# Changelog

> This file tracks **software releases**.
> For the monthly tool-registry update log see
> [`update/REGISTRY_CHANGELOG.md`](update/REGISTRY_CHANGELOG.md).

bioflow follows **Semantic Versioning** starting at 0.2.0.  Minor
releases (0.X.0) may add features and tools; patch releases (0.X.Y)
ship bug fixes only.  Breaking changes to the documented public API
(`bioflow.stage / pipeline / set_workspace / set_backend`, the
`bioflow` CLI surface, and tool YAML schema) wait for a major bump.

---

## [Unreleased]

### Fixed — clear error for shell-unsafe external input filenames
- An external input file whose **basename** contained a space or shell
  metacharacter silently corrupted the recipe's command — bioflow mounts
  the file's parent at the space-free `/inputs/<n>` and splices the
  basename in unquoted, and it can't be quoted generically because many
  recipes wrap the whole command in `bash -c '…'`.  (A spaced *directory*
  was already fine — only the basename survives into the command.)
- `_collect_external_mounts` now raises an actionable `ValueError`
  naming the offending characters and telling the user to rename /
  symlink to a safe name.
- Tests: +12 (`tests/unit/test_unsafe_paths.py`), incl. confirmation
  that spaced *directories* and workspace-internal paths are unaffected.

### Fixed — stage_timeout now actually bounds runtime
- **Latent bug**: `run_plan(stage_timeout=…)` never worked.  The log
  loop (`container.logs(stream=True, follow=True)`) blocks until the
  container exits, so the subsequent `container.wait(timeout=…)` — a
  docker-py HTTP read timeout, not a runtime cap — could never fire for
  a runaway container; it would hang forever.
- `DockerBackend.run` now starts a watchdog `threading.Timer` that
  `container.kill()`s the stage when the timeout elapses, returning the
  conventional exit code **124** with a clear message.
- Tests: +3 (`tests/unit/test_docker_timeout.py`, fake-container based,
  deterministic).

### Fixed — DockerBackend now clamps CPU/RAM to host capacity
- **Bug the full-pipeline e2e caught**: a stage declaring `cpu=8` (e.g.
  SPAdes in `prokaryote_assembly`) failed to even *start* on any host
  with fewer cores — Docker rejects a container whose `--cpus` exceeds
  the host count ("range of CPUs is from 0.01 to N.00"), so all 3 retry
  attempts died instantly.  Passed locally (12 cores) but failed on the
  4-core CI runner — and would hit any user on a small workstation.
- `DockerBackend.run` now clamps the requested CPU to the host core count
  and RAM to ~90% of host memory (`_clamp_resources`), so an
  over-ambitious resource request degrades to "use what's available"
  instead of crashing.
- Tests: +5 (`tests/unit/test_resource_clamp.py`).

### Added — first full-pipeline end-to-end test
- `tests/integration/test_full_pipeline_e2e.py`: runs the **entire**
  `prokaryote_assembly` recipe (fastp → SPAdes → QUAST → Prokka) against
  real BioContainers — the first time a complete pipeline (not just a
  first stage, as the smoke matrix does) is validated end-to-end.
- New `data/test/phix_small/` fixture: phiX174 (`NC_001422.1`, 5386 bp) +
  1000 wgsim-simulated 150 bp pairs (~56×, seed 42 → deterministic).
  phiX assembles into a single ~5.4 kb contig in <1 min, so the whole
  chain finishes in ~45 s.
- Asserts real data flow: assembled contig length 4.5–6 kb, QUAST
  `report.tsv`, and Prokka annotation with ≥1 CDS.  Verified locally
  (phiX → 1 contig 5377 bp, 6 CDS).
- Wired into the nightly-smoke workflow as a second step.

## [0.2.1] — 2026-06-12

> **Why upgrade from 0.2.0**: the `v0.2.0` tag predated the registry
> freshness fix, so the 0.2.0 wheel bundled a registry whose
> `quay.io/biocontainers/*` tags had been garbage-collected from Quay —
> `rnaseq_deg`, `chip_seq`, `atac_seq`, `eukaryote_assembly`,
> `metagenome_assembly`, and others would fail at run time with "image
> not found".  **0.2.1 ships the repaired, 107/107-pinned registry**, so
> recipes actually pull their containers.  Everything below landed after
> the 0.2.0 cut and is new to PyPI users here.

### Changed — nightly smoke matrix expanded (3 → 5 recipes)
- Added real-container smoke cases for **chip_seq** (TrimGalore — a
  container family shared by chip/atac/methylation, previously
  unexercised) and **germline_variants** (validates the variant recipe's
  fastp wiring).  All five pass against real BioContainers locally
  (~90 s) — more of the "522 mostly-mock tests" critique closed with
  genuine end-to-end coverage.

### Changed — mypy type-checking is now blocking
- Fixed all 33 mypy errors across 7 modules (Rich `TaskID` optionals in
  the progress bars, `dict[str, Any]` run kwargs, anthropic/openai/docker
  SDK union + missing-stub noise, a loop-variable shadow in
  `cli/update.py`).  `mypy bioflow --ignore-missing-imports` now reports
  **0 errors**.
- CI's `typecheck` job drops `continue-on-error` — a new type error now
  fails the build, closing the "advisory only" gap.

### Added — nf-core concordance benchmark (harness + methodology)
- `scripts/compare_nfcore.py` (new, stdlib-only): scores agreement
  between a bioflow output and the matching nf-core output —
  **Jaccard + genotype concordance** on normalised VCF sites
  (vs nf-core/sarek), and **Spearman ρ** of per-gene counts
  (vs nf-core/rnaseq).  Optional `--min-jaccard` / `--min-rho` gate for
  CI.
- `docs/benchmarks/nfcore-concordance.md`: golden datasets
  (GIAB HG002 chr20; nf-core/rnaseq chr22), method, and initial
  acceptance thresholds.
- `.github/workflows/nfcore-concordance.yml`: manually-dispatched job
  (not a per-PR gate — a full run needs staged references).
- Honesty note: bioflow ships the *scoring* half (committed + tested);
  the *production* half (running both pipelines on a machine with the
  references) is operator-run and documented.
- Tests: +13 (`tests/unit/test_compare_nfcore.py`).

### Added — GPU passthrough + Podman runtime
- `@stage(..., gpu=True)` (and a tool YAML's `resources.gpu`) now attach
  all host GPUs to that stage's container via a Docker `DeviceRequest`
  (the API equivalent of `--gpus all`); needs the NVIDIA Container
  Toolkit, and degrades to a warning on CPU-only hosts rather than
  failing.  Threaded through `Stage`, the `@stage` decorator, and the
  preset `run_plan` path.
- `DockerBackend` works with **Podman**: it honours `BIOFLOW_DOCKER_HOST`
  / `DOCKER_HOST` (point it at the Podman API socket) and an optional
  `base_url`, and reads `BIOFLOW_CONTAINER_RUNTIME`.
- `bioflow doctor` recognises Podman as a Docker alternative — the
  `docker_cli` / `docker_daemon` checks fall back to `podman` and report
  which runtime they found.
- Tests: +10 (`tests/unit/test_gpu_podman.py`).  Backend `run()` gains a
  `gpu` kwarg (the `ContainerBackend` protocol + MockBackend updated).

### Added — reference-DB catalog expansion + refgenie manifest
- `bioflow/core/db.py` catalog gains the references real recipes need:
  GATK known-sites `dbsnp_grch38` + `mills_indels_grch38` (BQSR/VQSR),
  `encode_blacklist_grch38` (ChIP/ATAC peak filtering), and
  `gencode_grch38` (STAR/Salmon/featureCounts annotation).
- Catalog entries now carry `genome` + `asset` tags, and a new
  `refgenie_manifest()` / `bioflow db manifest` emits a
  [refgenie](https://refgenie.databio.org/)-compatible JSON mapping
  `<genome>/<asset>` → catalogued DB, so labs already standardised on
  refgenie can see which existing assets satisfy a bioflow requirement.
- Tests: +5 (`tests/unit/test_db.py`).

### Added — rnaseq_deg depth: GO enrichment + MultiQC
- `rnaseq_deg` extended from 4 → 6 stages:
  - **`enrich_go`** — GO enrichment on the significant DEGs via gseapy's
    Enrichr query.  Symbol-based, so no organism-specific OrgDb package
    is needed; an awk numeric-regex guard on the `padj` column avoids the
    classic "NA-treated-as-0" false positive.
  - **`multiqc_report`** — aggregates every per-sample fastp + Salmon
    report into a single MultiQC HTML.
- DAG-shape test updated; recipe still runs end-to-end under MockBackend.

### Added — `joint_genotyping` recipe (GATK cohort best practice)
- New 7-stage recipe (`bioflow/recipes/variant_calling/joint_genotyping.py`)
  implementing the canonical GATK **joint-genotyping** workflow for
  cohorts, where `germline_variants` only does single-sample direct
  calling:
  - **per sample (fan-out)**: fastp → BWA-MEM → MarkDuplicates →
    HaplotypeCaller `-ERC GVCF`
  - **cohort (converge)**: CombineGVCFs → GenotypeGVCFs →
    best-practice hard filtering (separate SNP / INDEL filters) → SnpEff
- Takes a `sample_id,fastq_r1,fastq_r2` sample sheet and uses `.starmap`
  to run the per-sample stages in parallel before converging on the
  joint steps — the production pattern reviewers expect for population
  and family studies, and a worked example of bioflow's fan-out.
- Recipe count 19 → 20 (12 per-pipeline).  Tests: +3 (registration, DAG
  shape, MockBackend e2e).

### Added — run provenance (RO-Crate + PROV-style JSON)
- `bioflow/core/provenance.py` (new): every recipe run records, per
  stage, the container **image + content digest**, the exact
  **command**, every **input file's SHA-256 + size**, **start/end**
  timestamps, exit code, and the bioflow version.
- At the end of a run the workspace gains two self-describing files:
  - `provenance.json` — flat, human-readable run record
  - `ro-crate-metadata.json` — an [RO-Crate 1.1](https://www.researchobject.org/ro-crate/)
    research object (the de-facto packaging standard for computational
    workflow runs), so the output directory is consumable by reviewers
    and downstream tools directly.
- Wired into `bioflow recipe run` (on by default; `--no-provenance` to
  skip).  Opt-in and **zero-cost when off** — the SDK hot path pays
  nothing unless a recorder is installed, and provenance errors degrade
  to warnings rather than aborting the science.
- New `bioflow provenance show <workspace>` command (+ `--json`) renders
  the recorded run: per-stage image, pinned digest, exit status, and
  input hashes.  Builds directly on the digest-pinning work — pinned
  tools show their `sha256:…` in the provenance.
- Tests: +14 (`tests/unit/test_provenance.py`); verified end-to-end
  against real Docker (digest resolved from the local image, RO-Crate
  validates structurally).

### Fixed — registry freshness (stale BioContainer tags)
- **Discovery**: an audit during digest-pinning found that ~half the
  registry's `quay.io/biocontainers/*` image tags had 404'd.  Quay
  rotates each package's `--<buildhash>_<n>` build suffix and garbage-
  collects the old ones, so dozens of recipes (chip_seq, atac_seq,
  eukaryote_assembly, metagenome_assembly, rnaseq_deg's Salmon stage,
  …) would have failed at run time with "image not found" — unrelated
  to the user's data.
- `scripts/refresh_tags.py` (new): audits every Quay BioContainer
  reference, and with `--apply` rewrites any dead tag to the newest
  *same-version* build (never changing the upstream software version).
  Non-Quay images and versions that have left Quay entirely are
  reported for manual review.
- Applied: **34 registry tool YAMLs** + **7 recipe-hardcoded images**
  (bowtie2, bracken, flye, macs3, medaka, metabat2, tobias) re-pointed
  to live tags.  Salmon's `1.10.3--hb950928_0` → `1.10.3--h45fbf2d_5`
  fixed separately (it broke the rnaseq_deg quant stage).
- Verified: the bumped images pull + run (e.g. `bowtie2 2.5.4`), and
  the nightly smoke matrix is green.

### Added — full digest pinning (registry now 100% content-addressed)
- Digest coverage raised from 5/110 → **107/107 active tools** in two
  passes.  The second pass resolved the 17 hold-outs:
  - **Version bumps** to the newest BioContainer of the same tool where
    the pinned version had left Quay: DESeq2 1.44→1.50.2, edgeR
    4.2→4.8.2, limma 3.60→3.66, clusterProfiler 4.12→4.18.4, topGO
    2.56→2.62, HOMER 4.11.1→5.1, Scanpy 1.10.1→1.7.2 (1.10 was never on
    Quay biocontainers), Comet 2024020→2026011, Percolator 3.06.1→3.7.1,
    InterProScan 5.67→5.59.
  - **Image-source switches**: methylKit and monocle3 moved off the
    multi-GB `bioconductor/bioconductor_full:RELEASE_3_18` (gone) to the
    dedicated `bioconductor-methylkit` / `r-monocle3` BioContainers;
    Cell Ranger tag `7.2.0`→`v7.2.0`; Seurat `5.0.1`→`5.0.0`.
  - **Deprecations**: MaxQuant joins MSFragger + FragPipe as
    `deprecated: true` — proprietary tools whose images are gone and
    which the `proteomics_dda` recipe does not use (it runs the
    open-source msconvert → Comet → Percolator stack).  The audit now
    skips deprecated tools.
- **CI `digest-audit` is now blocking** (was advisory): every active
  tool must carry an `image_digest`, so the registry can never silently
  rot again.
- `scripts/refresh_tags.py` also reports `version_gone` and non-Quay
  images for these manual cases.

### Added — Bioconda recipe (prep)
- `conda-recipe/meta.yaml`: noarch-python Bioconda recipe (only
  bioflow's pure-Python stack is a conda dep; tools run as Docker
  containers).  Submission walkthrough in `docs/MAINTAINER.md` Part 7.
  Gated on the real-PyPI publish (the recipe sources the PyPI sdist).

### Changed — CI
- All workflows opt into the Node 24 runtime
  (`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`) ahead of the 2026-06-16 forced
  switch, silencing the Node 20 deprecation warnings.

### Fixed — nightly smoke
- `rnaseq_deg.qc_one` smoke assertion matched the stage's real output
  names (`<sample_id>_R1.clean.fq.gz`), fixing a false CI failure.

---

## [0.2.0] — 2026-06-05

First PyPI release.  Three months of 0.1.x work consolidated into a
single installable distribution + SemVer commitment.

> **PyPI distribution name**: ``bioflowkit``.  The namespace ``bioflow``
> was taken in 2018 by an unrelated dormant project, so we ship under
> ``bioflowkit`` on PyPI.  Everything else stays the same — Python
> ``from bioflow import stage`` still works, the ``bioflow`` CLI
> command is unchanged, and the repository remains
> ``github.com/hope9901/bioflow``.  Only the ``pip install`` argument
> reflects the alternate name.

### Added — `bioflow doctor`
- New CLI command + `bioflow.core.doctor` module: 12-point host
  self-check covering Python version, architecture, Docker CLI/daemon/
  socket, CPU/RAM/disk floors, GPU presence, registry loadability,
  `~/.bioflow/` writability, and workspace writability.
- Every check is independent and never raises — failures become
  `CheckResult(status="fail", fix="…")` so the rest of the report still
  runs.  Exit code is 1 when any check fails (warnings do not block).
- `--json` emits a structured `{summary, checks[]}` payload for CI;
  `--verbose` adds per-check detail blocks.
- README + `docs/install.md` updated to make `bioflow doctor` the first
  command a new user runs.
- Tests: +26 unit tests (`tests/unit/test_doctor.py`) covering each
  check + the CLI surface.

### Added — Container digest pinning
- `registry/schema.yaml`: optional `container.image_digest` field
  (pattern `^sha256:[0-9a-f]{64}$`).
- `bioflow.core.registry.ContainerSpec.pinned_image` returns
  `image@digest` when a digest is pinned; runner now passes that ref
  to the backend so silent upstream retags can't change recipe results.
- `scripts/pin_digests.py` resolves digests via `docker buildx
  imagetools inspect` (fallback: `docker manifest inspect`, then
  `docker pull`) and writes them back into YAML in-place, preserving
  comments via ruamel.yaml.  `--audit`, `--dry-run`, `--force`
  supported.
- CI adds an advisory `digest-audit` job that surfaces the
  pinned/unpinned count without failing the build (flip when bulk
  pinning is done).
- 5 high-traffic tools pinned in-tree (fastp / spades / quast / prokka /
  bwa) as a demonstration.
- Tests: +10 unit tests (`tests/unit/test_digest_pinning.py`) covering
  `pinned_image` semantics, schema validation, runner integration, and
  a live-registry regression guard.

### Added — Nightly recipe smoke matrix
- `tests/integration/test_recipe_smoke_matrix.py`: parametrized
  per-recipe smoke test that drives the lightest reachable stage of
  each recipe against a real BioContainer (fastp on the ecoli_small
  fixture, abricate on the bundled reference FASTA, …).  Each entry
  asserts the container exited 0 and produced expected output files.
- `.github/workflows/nightly-smoke.yml`: schedule = `0 3 * * *`,
  Docker-enabled ubuntu runner, uploads JUnit XML.
- README gains a "nightly smoke" badge.

### Added — `bioflow run --resume` / `--fresh` + `bioflow status`
- `bioflow run` already auto-skipped checkpointed stages; this exposes
  the behaviour with explicit `--resume` (alias for default) and
  `--fresh` (delete `.bioflow_state.json` and re-run from scratch).
  Mutually exclusive.
- New `bioflow status <workdir>` command: human report or `--json` for
  completed_stages / failed_stages / artifacts.
- Tests: +7 unit tests (`tests/unit/test_run_resume.py`) — fault
  injection mid-pipeline, resume skips completed stages, `--fresh`
  re-runs all, and CLI status surface (empty / partial / JSON).

### Changed — Internal layout (no public API changes)
- `bioflow/sdk.py` (1278 lines, one file) → `bioflow/sdk/` package with
  9 focused modules: `_runtime` (workspace/backend globals), `_cache`
  (toggles + sentinel), `_hashing`, `_paths` (host↔container path
  translation + external bind mounts), `_parallel` (worker count +
  progress + retry bumps), `_result` (StageResult), `_stage` (Stage +
  fan-out + `@stage` decorator), `_pipeline` (Pipeline + `@pipeline`),
  `__init__` re-exports the public surface and the underscore-prefixed
  helpers the test suite still references.  Largest single file
  shrinks from 1278 → 522 lines.
- `bioflow/cli.py` (1417 lines) → `bioflow/cli/` package: `_app`
  (typer app + console + encoding bootstrap), per-command modules
  `hw`, `pipelines` (recommend/custom/run/status), `db`, `update`,
  `ncbi`, `recipe` (also owns `_parse_recipe_extra`), `llm`, `doctor`,
  `setup`.  `__init__` imports each module to trigger `@app.command`
  registration and re-exports `app` + `_parse_recipe_extra` for
  backwards compatibility.  Largest single file now 318 lines
  (`cli/update.py`).
- New `bioflow/cli/__main__.py` keeps `python -m bioflow.cli` working
  alongside the existing `bioflow` console-script entry point.
- Verified: 565 unit tests still pass, ruff clean, `bioflow doctor`
  reports 12/12 ok on the dev host.

### Added — PyPI distribution
- First release published to PyPI as ``bioflow``.  ``pip install
  bioflow`` now works from any directory, with the 110-tool registry +
  14 preset YAMLs bundled inside the wheel
  (`bioflow/_bundled_registry/`).
- `.github/workflows/release.yml`: tag-driven (`v*.*.*`) release
  pipeline — build → TestPyPI → PyPI → GitHub Release — using PyPI
  Trusted Publishing (OIDC) so no long-lived tokens live in the repo.
  Build step refuses to publish when `pyproject.toml::project.version`
  and `bioflow.__version__` disagree, and verifies the wheel ships
  `bioflow/sdk/`, `bioflow/cli/`, and `bioflow/_bundled_registry/`.
- `docs/MAINTAINER.md`: PyPI Trusted Publisher setup walkthrough +
  release procedure (tag, monitor, hotfix).

### Bumps
- Version: 0.1.14 → 0.2.0 (SemVer commitment starts here).

### Tests
- 522 → 565 (+43): doctor (+26), digest pinning (+10), resume (+7).

---

## [0.1.14] — 2026-05-15

### Added — documentation site (MkDocs → GitHub Pages)
- `mkdocs.yml` (Material theme) + `docs/` pages: index, install,
  quickstart, architecture, on top of the existing MAINTAINER /
  UPDATE_CADENCES / DESIGN docs.
- `scripts/gen_docs.py` — auto-generates `docs/reference/tools.md`
  (110 tools by category) and `docs/reference/recipes.md` (19 recipes
  with their DAGs) from the registry so the published docs never drift.
- `.github/workflows/docs.yml` — regenerates the reference pages,
  builds with `mkdocs build --strict`, and deploys to GitHub Pages on
  push to main (official actions/deploy-pages flow).
- `[project.optional-dependencies].docs` = mkdocs + mkdocs-material.
- README links to https://hope9901.github.io/bioflow/.

### Note
- Enable Pages once in the repo settings (Settings → Pages → Source:
  GitHub Actions) for the first deploy to publish.

### Bumps
- Version: 0.1.13 → 0.1.14

---

## [0.1.13] — 2026-05-15

### Added — real-data validation + distribution (TIER 1-B & TIER 2)

**First real-biology validation** (was: MockBackend + alpine only)
- `data/test/ecoli_small/real_R{1,2}.fastq.gz` — 500 high-quality
  paired reads (Phred 40), a third carrying adapters.
- `tests/integration/test_recipe_real_data.py` — pulls the real
  fastp BioContainer and runs it on the fixture: 1000 reads in,
  >800 survive, valid JSON report.  Also runs the
  `prokaryote_assembly` recipe's qc_trim stage against real Docker.
  **First time an actual bioinformatics tool has been validated
  end-to-end through the SDK.**

**Distribution**
- The bioflow self-image builds + runs:
  `docker build -f docker/core/Dockerfile -t bioflow .` →
  `docker run bioflow recipe list` shows all 19 recipes (~1 GB).
- **Fixed `pip install` deployment blocker**: the registry resolved as
  `./registry` relative to CWD, so a wheel install with no git checkout
  had no registry.  Now:
  - `pyproject.toml` force-includes `registry/` into the wheel as
    `bioflow/_bundled_registry` (110 tool YAMLs + presets + schema).
  - `bioflow.core.registry.default_registry_dir()` prefers `./registry`
    (dev) and falls back to the bundled copy.
  - Verified: clean-venv `pip install`, then `bioflow tools` from `C:\`
    lists all 110 tools and 19 recipes.
- `python -m build` + `twine check` PASS for sdist and wheel.

### Tests
- 519 → 522 (+3 registry-resolver unit tests).
- Integration: +2 real-fastp tests (Docker-gated).

### Bumps
- Version: 0.1.12 → 0.1.13 (synced stale `bioflow.__version__`).

---

## [0.1.12] — 2026-05-15

### Added — variant-calling pipeline (new category)
- New schema category `variant_calling` + `bioflow/pipelines/variant_calling.py`
- 4 new tools: `gatk4`, `bcftools`, `snpeff`, `freebayes`
- New recipe **`germline_variants`**:
  fastp → BWA-MEM → GATK MarkDuplicates+HaplotypeCaller →
  bcftools filter → SnpEff annotation.
  Fills the single largest workflow gap (resequencing / SNP calling).

### Added — recipes that use the 0.1.10/0.1.11 tools
Previously 30+ assembly / binning / polishing tools were registered but
unreachable from any one-liner.  Two new recipes wire them in:
- **`eukaryote_assembly`** — NanoPlot → Flye → Medaka → compleasm
  (long-read ONT/HiFi eukaryote assembly + polish + BUSCO QC)
- **`metagenome_assembly`** — fastp → MEGAHIT → minimap2 → MetaBAT2 →
  CheckM2 (metagenome assembly + genome binning + bin QC)

### Verified
- All 4 variant-calling images resolve via T1 freshness (no yanked).
- 3 new recipes execute end-to-end through MockBackend.

### Tests
- 510 → 519 (+9): 3 new e2e execution tests, 2 new DAG-shape entries,
  registry-total raised to ≥19.

### Bumps
- Tool count: 106 → 110 · Recipe count: 16 → 19 · Categories: 15 → 16
- Version: 0.1.11 → 0.1.12

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
