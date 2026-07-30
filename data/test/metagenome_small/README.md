# metagenome_small — synthetic 2-organism metagenome fixture

A tiny synthetic shotgun-metagenome for exercising the `metagenome_assembly`
recipe's **assemble → coverage → binning** stages without a multi-GB CheckM2
database or real reads.

- `reads_R1.fastq.gz` / `reads_R2.fastq.gz` — 4 200 read-pairs (100 bp, 350 bp
  insert) sampled at ~60× from two synthetic "genomes": `orgA` (8 kb, GC-rich)
  and `orgB` (6 kb, AT-rich). The GC contrast is what a real binner would use to
  separate them.

MEGAHIT assembles this into 2 contigs (~14 kb total); MetaBAT2 then computes a
depth table (both contigs at ~60×) and writes the `bins/` layout CheckM2
consumes.

**What it can't prove**: the binners emit *zero* bins here, and that's expected
— the sequences are random, so MaxBin2 finds none of its 107 single-copy marker
genes ("cannot be binned") and MetaBAT2 has too few contigs to cluster. Actual
bin content needs real gene-bearing genomes at many contigs, which don't fit in
git. So the guard stops at "each stage consumes the previous artifact and writes
the layout the next one reads"; MaxBin2's `maxbin.NNN.fasta → bins/bin.N.fa`
renaming is unit-tested separately, and full binning was verified once on real
E. coli + S. aureus during development.

Generated deterministically (`seed=17`).
