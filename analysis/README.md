# analysis/

This directory contains example output produced by bioflow cookbook recipes
on a real dataset.  It is included as a reference so you can see what
a completed run looks like before running bioflow on your own data.

## What is here

```
analysis/
  dickeya/        262-genome Dickeya pangenome + comparative-genomics run
                  produced by:
                  bioflow recipe run pangenome --taxon Dickeya --max 262
                  bioflow recipe run ani_matrix  --taxon Dickeya
                  bioflow recipe run phylogeny   --taxon Dickeya
                  bioflow recipe run gwas        ...
                  bioflow recipe run amr_vf_catalogue ...
                  bioflow recipe run cog_enrichment ...
```

Key output files:

| File | Description |
|---|---|
| `dickeya/summary.html` | Interactive HTML report covering all recipe outputs |
| `dickeya/roary/` | Pangenome core/accessory matrix (Roary) |
| `dickeya/ani/` | All-vs-all FastANI matrix + heatmap |
| `dickeya/phylogeny/` | IQ-TREE ML phylogeny |
| `dickeya/scoary/` | GWAS results (Scoary) |
| `dickeya/abricate/` | AMR / virulence factor catalogue |

## Reproducing this output

```bash
# Download assemblies
bioflow recipe run download_taxon --taxon Dickeya --max 262 --out ./out

# Run all comparative-genomics recipes
bioflow recipe run pangenome       --taxon Dickeya --max 262 --out ./out
bioflow recipe run ani_matrix      --taxon Dickeya --max 262 --out ./out
bioflow recipe run phylogeny       --taxon Dickeya --max 262 --out ./out
bioflow recipe run cog_enrichment  --taxon Dickeya --max 262 --out ./out
```

Results are cached by input hash.  A second run with the same inputs
completes in seconds.

## Data source

All genome assemblies are NCBI RefSeq public records.  No
patient data or private sequences are included.
