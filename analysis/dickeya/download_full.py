"""Download all Dickeya GCF genomes in batches (workaround for HTTP 414).

bioflow's download_genomes() puts all accessions into a single URL, which NCBI
rejects with 414 once you exceed ~30 accessions.  This script chunks the
accession list and stitches the per-batch ZIPs into one output dir.
"""
from __future__ import annotations
import sys, urllib.request, urllib.parse, zipfile, shutil, time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.ncbi import list_genomes, _stream_to_file, _api_key  # noqa: E402

OUT = ROOT / "analysis" / "dickeya" / "genomes_full"
OUT.mkdir(parents=True, exist_ok=True)
TMP = OUT / "_zips"; TMP.mkdir(exist_ok=True)

print("Querying NCBI for all Dickeya assemblies …")
assemblies = list_genomes("dickeya", max_results=2000)
gcf = [a for a in assemblies if a.accession.startswith("GCF_")]
print(f"  total returned: {len(assemblies)}, GCF (RefSeq) unique: {len(gcf)}")

CHUNK = 25  # keep URL well under 4 KB
DATASETS = "https://api.ncbi.nlm.nih.gov/datasets/v2"
key_qs = (f"&api_key={_api_key()}" if _api_key() else "")

extracted_count = 0
for i in range(0, len(gcf), CHUNK):
    batch = [a.accession for a in gcf[i:i + CHUNK]]
    acc_str = ",".join(urllib.parse.quote(a) for a in batch)
    url = (
        f"{DATASETS}/genome/accession/{acc_str}/download"
        f"?hydrated=FULLY_HYDRATED&include_annotation_type=GENOME_FASTA{key_qs}"
    )
    zip_path = TMP / f"batch_{i//CHUNK:03d}.zip"
    if zip_path.exists() and zip_path.stat().st_size > 1000:
        print(f"  batch {i//CHUNK:03d}: cached")
    else:
        print(f"  batch {i//CHUNK:03d}: downloading {len(batch)} genomes ...", flush=True)
        t0 = time.time()
        _stream_to_file(url, zip_path)
        print(f"     -> {zip_path.stat().st_size/1e6:.1f} MB in {time.time()-t0:.1f}s")

    # Extract FNA files
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if not member.lower().endswith(".fna"):
                continue
            parts = Path(member).parts
            if len(parts) >= 3 and parts[0] == "ncbi_dataset" and parts[1] == "data":
                acc = parts[2]
                dest = OUT / f"{acc}.fna"
                if dest.exists():
                    continue
                with zf.open(member) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                extracted_count += 1

print(f"\nExtracted {extracted_count} new FNA files; total in {OUT}: "
      f"{len(list(OUT.glob('*.fna')))}")
print(f"Total size: {sum(p.stat().st_size for p in OUT.glob('*.fna'))/1e9:.2f} GB")
