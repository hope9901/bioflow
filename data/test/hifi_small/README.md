# hifi_small — synthetic HiFi long-read fixture

`hifi_reads.fastq.gz` is ~269 HiFi-style long reads (4 kb, ~0.3 % error, ~200×)
sampled from the circular phiX genome (`../phix_small/reference.fa`, wrapped so
reads span the origin). 28 KB.

Used by the `eukaryote_assembly` guard for the **`--set assembler=hifiasm`**
path: NanoPlot read QC → hifiasm → the recipe's GFA→FASTA awk yields a single
`assembly.fasta` contig (~9 kb).

**Only the hifiasm path is guarded.** Flye (the default assembler) crashes with
SIGFPE on a genome this small — its coverage/length math divides by zero below
its intended multi-Mb scale — so a tiny fixture can't exercise it. Medaka
polishing and compleasm BUSCO scoring are also excluded: Medaka needs a real
basecaller model and compleasm needs a multi-hundred-MB lineage DB. So the guard
stops at "reads QC'd → hifiasm produces assembly.fasta", the artifact the rest
of the chain consumes.

Generated deterministically (`seed=31`).
