"""262-genome Dickeya pangenome — Prokka batch + Roary.

Stages:
  1. Prokka × 262 in parallel (6 concurrent × 2 cpu each = full host)
     Cached: skip any sample whose .gff already exists.
  2. Stage all GFFs into a flat directory.
  3. Roary on all 262 GFFs (-p 8, -i 90 — slightly looser than default 95
     to keep distantly-related strains in the same gene families).
  4. Light-weight visualisation: pangenome pie + rarefaction.

Robust to interruption: re-running picks up where it left off.
"""
from __future__ import annotations
import sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
GENOMES  = ANALYSIS / "genomes_full"
PROKKA   = ANALYSIS / "prokka_full"; PROKKA.mkdir(exist_ok=True)
GFF_DIR  = ANALYSIS / "roary_full" / "_gff_in"; GFF_DIR.mkdir(parents=True, exist_ok=True)
ROARY    = ANALYSIS / "roary_full"; ROARY.mkdir(exist_ok=True)
WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

# Sample list = every .fna in genomes_full
samples = sorted(p.stem for p in GENOMES.glob("*.fna"))
print(f"Found {len(samples)} genomes to process")

# ── Phase 1: Prokka in parallel ─────────────────────────────────────────────

def prokka_one(sample: str) -> tuple[str, int, float]:
    out_gff = PROKKA / sample / f"{sample}.gff"
    if out_gff.exists() and out_gff.stat().st_size > 1000:
        return sample, 0, 0.0  # cached
    t0 = time.time()
    cmd = (
        f"prokka --outdir {WS_CTR}/prokka_full/{sample} "
        f"--prefix {sample} --cpus 2 --kingdom Bacteria "
        f"--genus Dickeya --usegenus --force --quiet "
        f"{WS_CTR}/genomes_full/{sample}.fna"
    )
    r = backend.run(
        image="staphb/prokka:1.14.6", command=cmd,
        mounts={WS_HOST: WS_CTR}, cpu=2, ram_gb=4, workdir=WS_CTR,
    )
    return sample, r.exit_code, time.time() - t0


print(f"\n=== Phase 1: Prokka × {len(samples)} (6 parallel × 2 cpu) ===")
phase_t0 = time.time()
done = 0; failed = []; cached = 0
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(prokka_one, s): s for s in samples}
    for fut in as_completed(futs):
        sid, rc, dt = fut.result()
        done += 1
        if dt == 0.0:
            cached += 1
        elif rc != 0:
            failed.append(sid)
        # Progress line every 5 completions or for failures
        if done % 5 == 0 or rc != 0:
            elapsed = time.time() - phase_t0
            rate = done / max(elapsed, 1)
            eta_s = (len(samples) - done) / max(rate, 1e-3)
            print(
                f"  [{done:3d}/{len(samples)}] +{sid:<25s} rc={rc} dt={dt:5.0f}s "
                f"| elapsed={elapsed/60:.1f}m  ETA={eta_s/60:.1f}m  "
                f"cached={cached} failed={len(failed)}",
                flush=True,
            )

print(f"\nProkka phase done in {(time.time()-phase_t0)/60:.1f} min")
print(f"  successful={done-len(failed)-cached}  cached={cached}  failed={len(failed)}")
if failed:
    print(f"  failed samples: {failed[:10]}{' ...' if len(failed)>10 else ''}")

# ── Phase 2: Stage GFFs flat for Roary ──────────────────────────────────────
print("\n=== Phase 2: Stage GFFs ===")
staged = 0
for s in samples:
    src = PROKKA / s / f"{s}.gff"
    dst = GFF_DIR / f"{s}.gff"
    if src.exists() and (not dst.exists() or dst.stat().st_size != src.stat().st_size):
        dst.write_bytes(src.read_bytes())
        staged += 1
print(f"  staged {staged} new GFF; total in {GFF_DIR}: {len(list(GFF_DIR.glob('*.gff')))}")

# ── Phase 3: Roary ──────────────────────────────────────────────────────────
print("\n=== Phase 3: Roary all-vs-all ===")
roary_out = ROARY / "out"
if roary_out.exists() and (roary_out / "summary_statistics.txt").exists():
    print(f"  Roary output already exists at {roary_out} — skipping (delete to rerun)")
else:
    t0 = time.time()
    r = backend.run(
        image="staphb/roary:3.13.0",
        command=(
            f"sh -c 'rm -rf {WS_CTR}/roary_full/out && "
            f"roary -p 8 -i 90 -f {WS_CTR}/roary_full/out "
            f"{WS_CTR}/roary_full/_gff_in/*.gff'"
        ),
        mounts={WS_HOST: WS_CTR}, cpu=8, ram_gb=28, workdir=WS_CTR,
        timeout=14400,   # 4-hour cap
    )
    print(f"  Roary exit={r.exit_code}  elapsed={(time.time()-t0)/60:.1f}m")
    if r.exit_code != 0:
        print((r.stderr or r.stdout)[-2000:])
        sys.exit(1)

# ── Phase 4: Visualize ──────────────────────────────────────────────────────
print("\n=== Phase 4: Visualize ===")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

stats = (roary_out / "summary_statistics.txt").read_text(encoding="utf-8")
buckets = {}
for line in stats.strip().splitlines():
    parts = line.split("\t")
    if len(parts) >= 3 and parts[0].lower() != "total genes":
        buckets[parts[0]] = int(parts[-1])
total = sum(buckets.values())

print("Pangenome composition:")
for k, v in buckets.items():
    print(f"  {k:<30s}{v:>8,}")
print(f"  {'TOTAL':<30s}{total:>8,}")

# Pangenome pie
fig, ax = plt.subplots(figsize=(7.5, 6.5), dpi=130)
ax.pie(
    list(buckets.values()),
    labels=[f"{k}\n(n={v:,})" for k, v in buckets.items()],
    autopct="%.1f%%", startangle=90,
    colors=["#1f77b4", "#aec7e8", "#ff7f0e", "#d62728"],
)
ax.set_title(f"Dickeya genus pangenome (n={total:,} clusters across 262 genomes)")
plt.tight_layout()
plt.savefig(ANALYSIS / "figures" / "pangenome_full_pie.png"); plt.close()

# Rarefaction
def _read_rtab(p): return pd.read_csv(p, sep="\t", header=None)
fig, ax = plt.subplots(figsize=(9, 5.5), dpi=130)
for label, fname in [
    ("Conserved (core) genes", "number_of_conserved_genes.Rtab"),
    ("Total (pan) genes",      "number_of_genes_in_pan_genome.Rtab"),
]:
    p = roary_out / fname
    if not p.exists(): continue
    mat = _read_rtab(p)
    mean = mat.mean(axis=0); std = mat.std(axis=0)
    x = np.arange(1, len(mean)+1)
    ax.plot(x, mean, label=label, lw=1.8)
    ax.fill_between(x, mean-std, mean+std, alpha=0.25)
ax.set_xlabel("Number of genomes")
ax.set_ylabel("Number of gene clusters")
ax.set_title(f"Dickeya pangenome growth (n=262 GCF assemblies)")
ax.legend(); ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(ANALYSIS / "figures" / "pangenome_full_curve.png"); plt.close()

print("Figures written to analysis/dickeya/figures/")
print("\nALL DONE.")
