# Quick start

## List and inspect recipes

```bash
bioflow recipe list                      # every recipe + stage count
bioflow recipe show prokaryote_assembly  # render the DAG without running
bioflow recipe run prokaryote_assembly --dry-run
```

## Run a recipe

Recipes take their inputs as `--key value` options.  Missing required
inputs produce a clear error telling you what to pass.

=== "Prokaryote assembly"

    ```bash
    bioflow recipe run prokaryote_assembly \
      --r1 reads_R1.fastq.gz --r2 reads_R2.fastq.gz \
      --sample-id ecoli_42 --out ./out
    ```

=== "RNA-seq DEG"

    ```bash
    bioflow recipe run rnaseq_deg \
      --sample-sheet samples.csv --transcriptome ref.fa \
      --out ./out
    ```

=== "Variant calling"

    ```bash
    bioflow recipe run germline_variants \
      --r1 sample_R1.fq.gz --r2 sample_R2.fq.gz \
      --reference genome.fa --snpeff-db Escherichia_coli_k12 \
      --sample-id sample01 --out ./out
    ```

=== "Pangenome (taxon-driven)"

    ```bash
    bioflow recipe run pangenome --taxon Dickeya --max 13 --out ./out
    ```

Recipes use **input-hash caching** automatically — a second run with the
same inputs returns in seconds.  Stages that declare it **retry with
bumped resources** on failure (e.g. SPAdes → 2× RAM on OOM).

## Reference databases

Some recipes need external databases (Kraken2 DB, BUSCO lineages, etc.).

```bash
bioflow db list                              # what's available
bioflow db fetch kraken2_standard_8gb --dest /refs
bioflow db verify kraken2_standard_8gb --dest /refs
```

## Programmatic use (Tier-A SDK)

```python
from bioflow import stage, pipeline, set_workspace
from bioflow.recipes import get

set_workspace("./out")
result = get("prokaryote_assembly")(
    r1="R1.fq.gz", r2="R2.fq.gz", out_dir="./out", sample_id="demo",
)
print(result.ok, result.out_dir)
```

See [`examples/recipes_quickstart.py`](https://github.com/hope9901/bioflow/blob/main/examples/recipes_quickstart.py)
for the call signature of every recipe.
