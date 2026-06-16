# gwas_small — pangenome-GWAS e2e fixture

A tiny synthetic Roary pan-genome + phenotype table for a full
end-to-end test of the `gwas` recipe (Scoary).

| File | What |
|---|---|
| `gene_presence_absence.csv` | Roary-format GPA: 12 genes × 10 samples |
| `traits.csv` | Scoary-format binary phenotype (`Resistant` 0/1) |

The 10 samples split 5 resistant / 5 susceptible.  The genes include
4 core (in all samples), one **perfectly associated** with resistance,
one anti-associated, and several random accessory genes — enough for
Scoary's Fisher's-exact test to find a real association in seconds.

Synthetic (seed 11) rather than derived from a Roary run, because the
`genomes_small` pair is near-identical (an all-core pan-genome has no
presence/absence variation for Scoary to test).

## Used by

`tests/integration/test_full_pipeline_e2e.py::test_gwas_full_chain`.
