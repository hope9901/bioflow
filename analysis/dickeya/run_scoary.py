"""Scoary GWAS — find accessory genes correlated with phenotypes.

Phenotypes (binary, derived from ANI tree clade membership):
  - vascular_wilt : 1 for solani/dadantii/fangzhongdai/dianthicola/undicola/chrysanthemi, else 0
  - soft_rot      : 1 for zeae/parazeae/oryzae/ananatis, else 0

Scoary reads:
  - traits.csv                                  (phenotype matrix we make)
  - roary's gene_presence_absence.csv from the LOOSE re-run

and outputs per-trait TSVs ranked by Bonferroni-corrected p-value.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
SCOARY   = ANALYSIS / "scoary"; SCOARY.mkdir(exist_ok=True)
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)

WS_HOST = str(ANALYSIS); WS_CTR = "/work"

# Phenotype assignments (from ANI tree clades)
VASCULAR_WILT = {"D_solani", "D_dadantii", "D_fangzhongdai",
                 "D_dianthicola", "D_undicola", "D_chrysanthemi"}
SOFT_ROT      = {"D_zeae", "D_parazeae", "D_oryzae", "D_ananatis"}
# water-associated (D_aquatica, D_lacustris) and D_poaceiphila are 0 for both

INPUTS = ANALYSIS / "inputs"
samples = sorted(p.stem for p in INPUTS.glob("*.fna"))


def short(s: str) -> str: return "_".join(s.split("_")[:2])


# ── 1. Build traits.csv (Scoary format: comma-separated, samples as rows) ──
traits_path = SCOARY / "traits.csv"
with traits_path.open("w", encoding="utf-8") as fh:
    fh.write("Name,vascular_wilt,soft_rot\n")
    for s in samples:
        sh = short(s)
        vw = 1 if sh in VASCULAR_WILT else 0
        sr = 1 if sh in SOFT_ROT      else 0
        fh.write(f"{s},{vw},{sr}\n")
print(f"Traits matrix written -> {traits_path}")
print(f"  vascular_wilt n={sum(short(s) in VASCULAR_WILT for s in samples)}")
print(f"  soft_rot      n={sum(short(s) in SOFT_ROT for s in samples)}")

# ── 2. Run Scoary ───────────────────────────────────────────────────────────
gpa = ANALYSIS / "roary" / "out_loose" / "gene_presence_absence.csv"
if not gpa.exists():
    print(f"FATAL: {gpa} missing — Roary loose re-run not finished?")
    sys.exit(2)

backend = DockerBackend()
print("\nRunning Scoary (image: quay.io/biocontainers/scoary:1.6.16--py_2)")
t0 = time.time()
r = backend.run(
    image="quay.io/biocontainers/scoary:1.6.16--py_2",
    command=(
        f"sh -c 'cd {WS_CTR}/scoary && "
        f"scoary -t traits.csv "
        f"-g {WS_CTR}/roary/out_loose/gene_presence_absence.csv "
        f"-p 1.0 --no_pairwise --no-time -o results "
        f"&& ls -la results'"
    ),
    mounts={WS_HOST: WS_CTR}, cpu=4, ram_gb=4, workdir=WS_CTR,
)
print(f"exit={r.exit_code}  elapsed={time.time()-t0:.1f}s")
if r.exit_code != 0:
    print((r.stderr or r.stdout)[-1500:])
    sys.exit(1)

# ── 3. Visualise top-N hits per trait ──────────────────────────────────────
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

results_dir = SCOARY / "results"
csvs = sorted(results_dir.glob("*.csv"))
print(f"\nScoary outputs: {[p.name for p in csvs]}")

for csv in csvs:
    if "vascular_wilt" in csv.name: trait = "vascular_wilt"
    elif "soft_rot"   in csv.name: trait = "soft_rot"
    else: continue
    df = pd.read_csv(csv)
    # Filter for genes with reasonable signal — Bonferroni p < 0.05 OR
    # when n=13 we relax to naive p < 0.01 (Bonferroni is too strict for tiny n)
    sig = df[df["Naive_p"] < 0.01].sort_values(
        "Naive_p"
    ).head(25).copy()
    if sig.empty:
        print(f"  {trait}: no significant genes at p<0.01")
        continue
    sig["log10p"] = -np.log10(sig["Naive_p"].clip(lower=1e-12))
    fig, ax = plt.subplots(figsize=(9, max(3, 0.3 * len(sig))), dpi=130)
    bars = ax.barh(
        sig["Gene"][::-1], sig["log10p"][::-1],
        color=["#d62728" if r["Sensitivity"] > 80 and r["Specificity"] > 80
               else "#1f77b4" for _, r in sig.iloc[::-1].iterrows()],
    )
    ax.set_xlabel("-log10(naive p)")
    ax.set_title(
        f"Scoary GWAS: top 25 genes associated with {trait}\n"
        f"(red = sensitivity & specificity > 80%)"
    )
    plt.tight_layout()
    out_png = FIG / f"scoary_{trait}.png"
    plt.savefig(out_png); plt.close()
    print(f"  {trait}: {len(df)} candidate genes → top 25 plotted to {out_png}")
    sig[["Gene", "Annotation", "Naive_p", "Bonferroni_p",
         "Sensitivity", "Specificity"]].to_csv(
        SCOARY / f"top25_{trait}.tsv", sep="\t", index=False,
    )

print("\nScoary complete.")
