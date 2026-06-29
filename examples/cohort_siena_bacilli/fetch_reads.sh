#!/usr/bin/env bash
# Fetch the 6 endospore-forming Bacilli isolates (BioProject PRJNA862062)
# used by the cohort example, straight from ENA.
#
#   Data: McLoon et al. 2022, Microbiol Resour Announc, doi:10.1128/mra.00874-22
#   (6 soil isolates sequenced on Illumina NextSeq; ~3-4M read pairs each).
#
# Usage:
#   ./fetch_reads.sh            # full reads (~hundreds of MB total)
#   SUBSAMPLE=100000 ./fetch_reads.sh   # first N read pairs each (fast demo)
#
# Requires: curl.  Subsampling additionally needs seqkit (or run it inside the
# bioflow fastp container).  Files land in ./data/ matching samples.csv.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data

# sample_id -> SRA run accession (PRJNA862062; SAMN29936620..625)
declare -A RUN=(
  [SC107]=SRR20695163
  [SC111]=SRR20695162
  [SC112]=SRR20695161
  [SC114]=SRR20695160
  [SC116]=SRR20695159
  [SC117]=SRR20695158
)

ena_urls() {  # echo the two fastq_ftp URLs for a run accession
  # ENA prepends run_accession, and the two URLs are ';'-joined — pull the
  # *.fastq.gz tokens directly so column layout can't trip us up.
  curl -fsSL "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=$1&result=read_run&fields=fastq_ftp&format=tsv" \
    | grep -oE '[^;[:space:]]+fastq\.gz'
}

for sid in "${!RUN[@]}"; do
  run="${RUN[$sid]}"
  echo "== $sid ($run) =="
  mapfile -t urls < <(ena_urls "$run")
  i=1
  for u in "${urls[@]}"; do
    [ -n "$u" ] || continue
    out="data/${sid}_R${i}.fastq.gz"
    if [ -n "${SUBSAMPLE:-}" ]; then
      # stream-download, keep first SUBSAMPLE read pairs (4 lines/read), re-gzip
      curl -fsSL "https://${u}" | zcat | head -n $(( SUBSAMPLE * 4 )) | gzip > "$out"
    else
      curl -fsSL "https://${u}" -o "$out"
    fi
    echo "   -> $out"
    i=$((i + 1))
  done
done
echo "Done. Now: bioflow cohort prokaryote_assembly -s samples.csv -o out -j 2"
