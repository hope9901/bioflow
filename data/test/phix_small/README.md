# phix_small — full-pipeline e2e fixture

A tiny but **real and assemblable** dataset for validating an entire
recipe end-to-end (not just its first stage like the smoke matrix).

## Contents

| File | What |
|---|---|
| `reference.fa`    | phiX174 genome (NCBI `NC_001422.1`, 5386 bp) |
| `sim_R1.fastq.gz` | 1000 simulated 150 bp R1 reads (~56× coverage) |
| `sim_R2.fastq.gz` | 1000 simulated 150 bp R2 reads |

phiX174 is the canonical tiny genome (the Illumina sequencing spike-in).
At ~56× it assembles cleanly into a single ~5.4 kb contig in well under a
minute, so a complete `fastp → SPAdes → QUAST → Prokka` run finishes in a
few minutes while exercising real biology.

## How it was generated (reproducible)

```bash
# reference: phiX174 from NCBI
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi\
?db=nuccore&id=NC_001422.1&rettype=fasta&retmode=text" -o reference.fa

# paired reads via the wgsim BioContainer (fixed seed → deterministic)
docker run --rm -v "$PWD":/d -w /d \
  quay.io/biocontainers/wgsim:1.0--h577a1d6_10 \
  wgsim -N 1000 -1 150 -2 150 -S 42 -e 0.005 -r 0 \
        reference.fa sim_R1.fastq sim_R2.fastq
gzip sim_R1.fastq sim_R2.fastq
```

Seed `42` + `-r 0` (no extra mutations) make the reads deterministic, so
the assembly is stable across runs.

## Used by

`tests/integration/test_full_pipeline_e2e.py` — runs the whole
`prokaryote_assembly` recipe against real BioContainers and asserts the
assembly (~5.4 kb single contig), QUAST report, and Prokka annotation.
