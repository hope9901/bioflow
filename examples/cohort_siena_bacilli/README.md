# Cohort example — 6 soil Bacilli isolates (real published data)

A worked `bioflow cohort` example that fans the **`prokaryote_assembly`**
recipe across **6 real bacterial isolates** from a published genome
announcement, each producing its own assembly + Prokka annotation, with one
aggregated MultiQC report at the end.

## Dataset

Based on articles retrieved from PubMed: McLoon *et al.*, "Draft Genome
Sequences for 6 Isolates of Endospore-Forming Class *Bacilli* Species Isolated
from Soil from a Suburban, Wooded, Developed Space," *Microbiology Resource
Announcements* (2022) — [DOI](https://doi.org/10.1128/mra.00874-22).

6 isolates from a campus wooded area, sequenced on Illumina NextSeq
(~3–4M paired reads each; genomes 4.4–6.1 Mbp). Raw reads are public under
**BioProject PRJNA862062**:

| sample_id | Species | BioSample | SRA run | read pairs |
|-----------|---------|-----------|---------|------------|
| SC107 | *Bacillus pseudomycoides* | SAMN29936620 | SRR20695163 | 3.18M |
| SC111 | *Rossellomorea* sp. | SAMN29936621 | SRR20695162 | 3.77M |
| SC112 | *Peribacillus frigoritolerans* | SAMN29936622 | SRR20695161 | 4.10M |
| SC114 | *Priestia megaterium* | SAMN29936623 | SRR20695160 | 3.58M |
| SC116 | *Paenibacillus* sp. | SAMN29936624 | SRR20695159 | 3.51M |
| SC117 | *Lysinibacillus fusiformis* | SAMN29936625 | SRR20695158 | 4.13M |

## Run it

```bash
# 1. Fetch reads from ENA.  A subsampled fetch keeps the demo fast + small:
SUBSAMPLE=100000 ./fetch_reads.sh        # first 100k read pairs per isolate
#    (omit SUBSAMPLE for the full reads — hundreds of MB total)

# 2. Fan prokaryote_assembly across all 6 isolates, 2 at a time:
bioflow cohort prokaryote_assembly -s samples.csv -o out -j 2

# Preview the per-sample plan without running anything:
bioflow cohort prokaryote_assembly -s samples.csv -o out --dry-run
```

Each isolate lands in `out/<sample_id>/` (its own assembly, QUAST, Prokka),
one sample failing does not abort the rest, and `out/cohort_multiqc/` holds
the aggregated QC report.

> Heads-up: a full 6-isolate assembly pulls several multi-GB BioContainers and
> is CPU/RAM-heavy. Start with `SUBSAMPLE` and/or `-j 1`, and on a cluster use
> `BIOFLOW_BACKEND=singularity` so no Docker daemon is needed.
