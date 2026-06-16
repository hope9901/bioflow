# rnaseq_small — RNA-seq DEG e2e fixture

A tiny synthetic differential-expression dataset for a full end-to-end
test of the `rnaseq_deg` recipe (fastp → Salmon → DESeq2 → enrichment →
MultiQC).

| File | What |
|---|---|
| `transcriptome.fa` | 60 synthetic transcripts (300–800 bp) |
| `{ctl1,ctl2,trt1,trt2}_R{1,2}.fastq.gz` | 4 samples (2 control, 2 treated), paired 75 bp reads |

10 transcripts are ~4× up-regulated in the treated samples, so DESeq2
recovers real signal (e.g. `tx0001` → log2FC ≈ 2).  Counts are small
(~4–7k read pairs/sample) so Salmon + DESeq2 finish in seconds.

The **sample sheet is built by the test at run time** (with absolute
paths to these files) rather than committed, since a committed sheet
would hard-code one machine's paths.

## Used by

`tests/integration/test_full_pipeline_e2e.py::test_rnaseq_deg_full_chain`.
