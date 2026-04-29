"""Build a 262-strain core-gene supermatrix for IQ-TREE.

Roary's `-e -n` mode wasn't requested in the full-pangenome run, so we
build the alignment ourselves from gene_presence_absence.csv:

  1. Pick 50 single-copy core genes — present in ≥99% of strains,
     exactly one copy each (from gene_presence_absence.csv).
  2. For each, pull every strain's nucleotide CDS from its Prokka .ffn.
  3. MAFFT each gene independently (parallel, inside a MAFFT container).
  4. Concatenate to form the supermatrix.
"""
from __future__ import annotations
import sys, time, gzip
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
PROKKA   = ANALYSIS / "prokka_full"
GPA_CSV  = ANALYSIS / "roary_full" / "out" / "gene_presence_absence.csv"
ALI_DIR  = ANALYSIS / "phylogeny_full"; ALI_DIR.mkdir(exist_ok=True)
GENE_FA  = ALI_DIR / "_genes_unaligned"; GENE_FA.mkdir(exist_ok=True)
GENE_AL  = ALI_DIR / "_genes_aligned"; GENE_AL.mkdir(exist_ok=True)

WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

# ── 1. Pick 50 single-copy core genes ───────────────────────────────────────
import pandas as pd
print("Loading gene_presence_absence.csv …")
gpa = pd.read_csv(GPA_CSV, low_memory=False)
meta_cols = {"Gene", "Non-unique Gene name", "Annotation", "No. isolates",
             "No. sequences", "Avg sequences per isolate", "Genome Fragment",
             "Order within Fragment", "Accessory Fragment",
             "Accessory Order with Fragment", "QC", "Min group size nuc",
             "Max group size nuc", "Avg group size nuc"}
sample_cols = [c for c in gpa.columns if c not in meta_cols]
N = len(sample_cols)
print(f"  {len(gpa):,} clusters × {N} strains")

# A gene is single-copy core if:
#   - present in ≥ N*0.99 strains
#   - "No. sequences" == "No. isolates" (i.e. one copy per strain)
sc_core = gpa[
    (gpa["No. isolates"] >= int(N * 0.99))
    & (gpa["No. sequences"] == gpa["No. isolates"])
].copy()
print(f"  {len(sc_core):,} single-copy core genes (≥{int(N*0.99)}/{N})")

# Take 50 with the longest median nucleotide length (more phylogenetic signal)
if "Avg group size nuc" in sc_core.columns:
    sc_core = sc_core.sort_values("Avg group size nuc", ascending=False)
SELECT = sc_core.head(50)
print(f"  Selected {len(SELECT)} for the supermatrix")

# ── 2. For each chosen gene, extract per-strain CDS from .ffn files ─────────
# Prokka .ffn: nucleotide CDS, header ">locus_tag annotation"
# We need a locus_tag → strain map and a strain → ffn file map.
print("\nIndexing all strain .ffn files …")
strain_ffn: dict[str, dict[str, tuple[str, str]]] = {}
for s in sample_cols:
    ffn = PROKKA / s / f"{s}.ffn"
    if not ffn.exists():
        continue
    seqs: dict[str, tuple[str, str]] = {}
    with ffn.open() as fh:
        cur_id = None; cur = []
        for line in fh:
            if line.startswith(">"):
                if cur_id: seqs[cur_id] = ("".join(cur), "")
                cur_id = line[1:].split()[0]
                cur = []
            else:
                cur.append(line.rstrip())
        if cur_id: seqs[cur_id] = ("".join(cur), "")
    strain_ffn[s] = seqs

print(f"  Indexed {len(strain_ffn)} strains.")

# Now write per-gene FASTAs (one file per gene with one sequence per strain)
print("\nWriting per-gene FASTAs …")
written = 0
gene_lens: dict[str, int] = {}
for _, row in SELECT.iterrows():
    g = row["Gene"]
    out = GENE_FA / f"{g}.fna"
    if out.exists() and out.stat().st_size > 0:
        # measure length from first seq
        with out.open() as fh:
            for line in fh:
                if not line.startswith(">"):
                    gene_lens.setdefault(g, len(line.rstrip()))
                    break
        continue
    rec_count = 0
    with out.open("w") as oh:
        for s in sample_cols:
            lt = row[s]
            if not isinstance(lt, str) or not lt.strip():
                continue
            lt = lt.split()[0]
            seq_data = strain_ffn.get(s, {}).get(lt)
            if not seq_data:
                continue
            seq = seq_data[0]
            if not seq:
                continue
            oh.write(f">{s}\n{seq}\n")
            rec_count += 1
            gene_lens.setdefault(g, len(seq))
    written += 1

print(f"  Wrote {written} per-gene FASTAs.")

# ── 3. MAFFT each gene in parallel inside a container ──────────────────────
# Use the standard MAFFT image
print("\nRunning MAFFT on each gene (8 parallel) …")


def mafft_one(gene: str) -> tuple[str, int, int]:
    out = GENE_AL / f"{gene}.aln"
    if out.exists() and out.stat().st_size > 0:
        return gene, 0, -1   # cached
    inp = GENE_FA / f"{gene}.fna"
    cmd = (
        f"sh -c 'mafft --auto --quiet --thread 1 "
        f"{WS_CTR}/phylogeny_full/_genes_unaligned/{gene}.fna "
        f"> {WS_CTR}/phylogeny_full/_genes_aligned/{gene}.aln'"
    )
    r = backend.run(
        image="staphb/mafft:7.520",
        command=cmd, mounts={WS_HOST: WS_CTR}, cpu=1, ram_gb=2, workdir=WS_CTR,
    )
    return gene, r.exit_code, out.stat().st_size if out.exists() else 0


genes = sorted(gene_lens.keys())
print(f"  {len(genes)} genes to align …")
done = 0; failed = []
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(mafft_one, g): g for g in genes}
    for fut in as_completed(futs):
        g, rc, sz = fut.result()
        done += 1
        if rc != 0 and sz != -1:
            failed.append(g)
        if done % 5 == 0:
            print(f"    [{done:3d}/{len(genes)}]  rc={rc}  size={sz}", flush=True)
print(f"  MAFFT done. failed={len(failed)}")
if failed:
    print(f"  Failed genes: {failed[:10]}")

# ── 4. Concatenate aligned genes per strain ─────────────────────────────────
print("\nConcatenating supermatrix …")
strain_seqs: dict[str, list[str]] = {s: [] for s in sample_cols}
total_len = 0; included = 0
for g in genes:
    aln = GENE_AL / f"{g}.aln"
    if not aln.exists() or aln.stat().st_size == 0:
        continue
    # parse alignment
    rec: dict[str, list[str]] = {}
    cur = None
    with aln.open() as fh:
        for line in fh:
            if line.startswith(">"):
                cur = line[1:].split()[0]; rec[cur] = []
            else:
                rec[cur].append(line.rstrip())
    if not rec:
        continue
    seq_lens = {len("".join(v)) for v in rec.values()}
    if len(seq_lens) != 1:
        print(f"    skip {g}: inconsistent length {seq_lens}")
        continue
    L = seq_lens.pop()
    # for each strain, append the aligned sequence (or all gaps if missing)
    for s in sample_cols:
        if s in rec:
            strain_seqs[s].append("".join(rec[s]))
        else:
            strain_seqs[s].append("-" * L)
    total_len += L
    included += 1

print(f"  {included}/{len(genes)} genes included; supermatrix length = {total_len:,} bp")

# Write final FASTA
out_super = ALI_DIR / "core_supermatrix.fna"
with out_super.open("w") as oh:
    for s in sample_cols:
        oh.write(f">{s}\n{''.join(strain_seqs[s])}\n")
print(f"\nWrote {out_super}  ({out_super.stat().st_size/1e6:.1f} MB)")
