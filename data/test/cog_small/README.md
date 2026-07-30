# cog_small — synthetic COG-enrichment fixture

A tiny synthetic input set for the `cog_enrichment` recipe (DIAMOND blastp of a
pangenome against COG references, then per-bucket functional-category
aggregation). No external database — DIAMOND builds its DB from `cog_reps.faa`
in-recipe, so this runs a **full** chain, not just a stage.

- `pangenome.faa` — 12 representative proteins named `gene_0001…gene_0012`, one
  per cluster in `../gwas_small/gene_presence_absence.csv` (reused as the GPA so
  the bucketing has real prevalence to work with).
- `cog_reps.faa` — the same 12 sequences, each headed `>gene_NNNN|COG10NN|ref`
  so DIAMOND's best hit carries a COG id the recipe can parse.
- `cog-24.def.tab` — the NCBI `cog-24.def.tab` layout (`COG_id<TAB>categories<TAB>
  name…`) mapping each COG to one functional-category letter (J/E/M/C/K/L/G/T).

Because each query is homologous to its own reference, all 12 map to a COG and a
category; the aggregation then splits them across core / shell buckets by the
GPA's `No. isolates` (genes 1–4 are in all 10 isolates → core, the rest → shell).

Generated deterministically (`seed=29`).
