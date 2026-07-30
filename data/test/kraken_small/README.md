# kraken_small — minimal custom Kraken2 database + reads

A hand-built 68 KB Kraken2 database (two synthetic 5–6 kb "genomes" under taxids
1000/1001, with a manually written `nodes.dmp` / `names.dmp`) plus 600 read-pairs
sampled from those genomes. Lets the `metagenomics_profile` classify step run in
CI without the multi-GB standard Kraken2 database.

- `db/hash.k2d`, `db/opts.k2d`, `db/taxo.k2d` — the built Kraken2 DB.
- `reads_R1.fastq.gz` / `reads_R2.fastq.gz` — 600 pairs; all classify (100 %).

The guard runs fastp → `kraken2 --db kraken_small/db` and checks a Kraken report
comes out.

**Bracken is not guarded.** Bracken 3.1 crashes walking the taxonomy of a DB this
small (`'int' object has no attribute 'level_num'`), even with a full
root→species lineage — it's a bug in Bracken's own tree code on a minimal DB, not
in the recipe. Real runs use the standard DB (`bioflow db fetch
kraken2_standard_8gb`), which ships Bracken's `kmer_distrib` files. So the guard
stops at classification, the step this fixture can prove.

Generated deterministically (seeds 37/41).
