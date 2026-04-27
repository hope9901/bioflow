"""Dickeya AMR + virulence factor cataloguing.

Scans every genome against three databases via ABRicate:
  - vfdb         : virulence factors (T3SS, pectinases, etc.)
  - card         : antibiotic resistance genes (CARD)
  - plasmidfinder: plasmid replicon types
Then builds gene-by-genome presence/absence heatmaps.
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
INPUTS   = ANALYSIS / "inputs"
ABR      = ANALYSIS / "abricate"; ABR.mkdir(exist_ok=True)
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)

WS_HOST  = str(ANALYSIS.resolve())
WS_CTR   = "/work"
backend  = DockerBackend()
DBS      = ["vfdb", "card", "plasmidfinder"]

samples = sorted(p.stem for p in INPUTS.glob("*.fna"))
print(f"Scanning {len(samples)} genomes against {len(DBS)} DBs ...")

for db in DBS:
    print(f"\n=== {db.upper()} ===")
    for s in samples:
        out = ABR / f"{s}.{db}.tsv"
        if out.exists() and out.stat().st_size > 0:
            print(f"  cached: {s}")
            continue
        cmd = (
            f"sh -c 'abricate --db {db} --threads 2 --quiet "
            f"{WS_CTR}/inputs/{s}.fna > {WS_CTR}/abricate/{s}.{db}.tsv'"
        )
        r = backend.run(
            image="staphb/abricate:1.2.0", command=cmd,
            mounts={WS_HOST: WS_CTR}, cpu=2, ram_gb=2, workdir=WS_CTR,
        )
        size = out.stat().st_size if out.exists() else 0
        print(f"  {s:<35s} exit={r.exit_code} bytes={size}")

# ─────────────────── Aggregate to presence/absence ──────────────────────────
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def short(s: str) -> str: return "_".join(s.split("_")[:2])


def load(db: str) -> pd.DataFrame:
    rows = []
    for s in samples:
        f = ABR / f"{s}.{db}.tsv"
        if not f.exists() or f.stat().st_size < 50:
            continue
        df = pd.read_csv(f, sep="\t")
        if df.empty: continue
        df["sample"] = short(s)
        rows.append(df)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


for db in DBS:
    df = load(db)
    if df.empty:
        print(f"\n{db}: no hits")
        continue

    # presence/absence pivot: row=gene, col=sample, value=identity
    pa = df.pivot_table(
        index="GENE", columns="sample", values="%IDENTITY",
        aggfunc="max", fill_value=0,
    )
    # Reorder columns to match ANI tree clade order (manually curated)
    clade_order = [
        "D_aquatica", "D_lacustris",                          # water-associated
        "D_chrysanthemi", "D_undicola", "D_dianthicola",      # mid clade
        "D_fangzhongdai", "D_dadantii", "D_solani",           # vascular wilt
        "D_poaceiphila",                                      # outgroup-like
        "D_oryzae", "D_ananatis", "D_zeae", "D_parazeae",     # soft-rot
    ]
    pa = pa.reindex(columns=[c for c in clade_order if c in pa.columns])

    # Sort genes: by total prevalence (most common first)
    pa = pa.assign(_n=(pa > 0).sum(axis=1)).sort_values("_n", ascending=False)
    pa = pa.drop(columns=["_n"])

    # Cap heatmap to top 80 genes for readability when there are many
    pa_disp = pa.head(80)

    n_g, n_s = pa_disp.shape
    fig, ax = plt.subplots(
        figsize=(max(6, 0.6 * n_s + 2), max(4, 0.18 * n_g + 1)), dpi=130,
    )
    masked = np.where(pa_disp.values > 0, pa_disp.values, np.nan)
    im = ax.imshow(masked, aspect="auto", cmap="YlGnBu", vmin=80, vmax=100)
    ax.set_xticks(range(n_s))
    ax.set_xticklabels(pa_disp.columns, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(n_g))
    ax.set_yticklabels(pa_disp.index, fontsize=6)
    ax.set_title(
        f"Dickeya x {db.upper()} — gene presence "
        f"({len(pa)} genes, top {n_g} shown; n_genomes={n_s})"
    )
    fig.colorbar(im, ax=ax, label="% identity", shrink=0.6)
    plt.tight_layout()
    out_png = FIG / f"abricate_{db}.png"
    plt.savefig(out_png); plt.close()
    print(f"\n{db}: {len(pa)} unique genes -> {out_png}")

    # Save full TSV table
    pa.to_csv(ABR / f"_summary_{db}.tsv", sep="\t")

# ─────────────────── Per-genome counts table ───────────────────────────────
print("\nPer-genome summary:")
print(f"  {'sample':<35s}" + "".join(f"  {db:>14s}" for db in DBS))
for s in samples:
    counts = []
    for db in DBS:
        f = ABR / f"{s}.{db}.tsv"
        if f.exists():
            n = sum(1 for _ in f.open()) - 1   # minus header
            n = max(n, 0)
        else:
            n = 0
        counts.append(n)
    print(f"  {s:<35s}" + "".join(f"  {n:>14d}" for n in counts))

print("\nDone.")
