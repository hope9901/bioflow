# bioflow

Bioinformatics pipeline platform — genome assembly/annotation and RNA-seq DEG —
orchestrated from Python over per-tool Docker containers.

## Status

Skeleton (step 1 of the implementation plan). Interfaces are defined; most
modules raise `NotImplementedError` until later steps land. See
`../.claude/plans/nested-leaping-karp.md` for the full plan.

## Two modes

- **recommend** — run a fixed preset (curated combination) per pipeline flavor.
- **custom**    — pick tools per stage from the list that is hardware-compatible
  on this host. The selection is saved to a YAML you can re-run verbatim.

## Two pipelines

1. **Genome Assembly & Annotation** — 6 stages
   read QC → assembly → assembly QC → repeat masking → structural annotation →
   functional annotation

2. **RNA-seq DEG** — 4 stages
   RNA-seq QC → alignment/quantification → DEG → GO/KEGG/GSEA enrichment

Each pipeline branches on `species` (prokaryote / eukaryote), `read_type`
(short / long HiFi / long ONT / hybrid), and `mode` (de_novo / resequencing).

## Quickstart (once implemented)

```bash
# Build the orchestrator image
docker compose -f docker/docker-compose.yml build

# Inspect hardware + available tools
docker compose run --rm bioflow hw
docker compose run --rm bioflow tools

# Recommended pipeline
docker compose run --rm bioflow recommend \
    --preset prokaryote_denovo_short \
    --config /workspace/examples/config_recommend.yaml

# Custom pipeline (interactive)
docker compose run --rm bioflow custom --pipeline rnaseq_deg -o my.yaml
docker compose run --rm bioflow run my.yaml
```

## Project layout

See plan file for the full directory tree. Key roots:

- `bioflow/` — Python package (orchestrator)
- `registry/` — tool + preset YAML registry
- `docker/` — orchestrator image & compose
- `data/` — workspace volume (inputs, refs, test data)
- `update/` — monthly Deep Research registry-update workflow
- `tests/` — unit + e2e tests

## Monthly update

`update/research_prompt.md` is the standard Deep Research prompt. Candidate
tools land in `update/candidates/YYYY-MM/`, are smoke-tested by
`update/benchmark.py`, and require **manual approval** before promotion to
`registry/tools/`. Registry changes are recorded in `update/CHANGELOG.md`.
