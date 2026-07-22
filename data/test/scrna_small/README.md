# scrna_small — synthetic 10x fixture

A tiny synthetic single-cell fixture for exercising the `scrna_seq` recipe's
`--set counter=kb` (kallisto | bustools) swap end-to-end without a multi-GB STAR
index or real 10x data.

- `genome.fa` — one 3 kb contig (`chr1`) with 3 genes (600 bp exons at 100, 1100,
  2100).
- `genes.gtf` — gene/transcript/exon annotation for geneA/geneB/geneC (+ strand).
- `whitelist.txt` — 8 barcodes (6 real cells + 2 decoys), 16 bp each.
- `reads_R1.fastq.gz` / `reads_R2.fastq.gz` — 600 read-pairs. R1 = 16 bp cell
  barcode + 12 bp UMI (10x v3 geometry); R2 = 90 bp cDNA drawn from a transcript.
  Cells 1–3 express geneA+geneB, cells 4–6 express geneB+geneC (2 reads/UMI).

`kb ref` + `kb count` on this yield a 6-cell × 3-gene matrix (300 UMIs) that
Scanpy loads directly. Generated deterministically (`seed=42`); regenerate with
the script in the `scrna_seq` swap commit if the geometry ever changes.
