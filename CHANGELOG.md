# Changelog

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
