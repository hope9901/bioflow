"""262-genome Scoary GWAS on the full Roary pangenome.

Phenotypes (binary, derived from FASTA-header species annotation):
  vascular_wilt   : dianthicola/solani/dadantii/fangzhongdai/
                    chrysanthemi/undicola              (n=202)
  soft_rot        : zeae/oryzae/ananatis/parazeae       (n= 46)
  is_solani       : species == solani                   (n= 51)
  is_dianthicola  : species == dianthicola              (n= 87)

With ~34k pangenome clusters × 4 traits, Bonferroni-corrected p<0.05
threshold ≈ 3.6e-7 — i.e. real statistical power.
"""
from __future__ import annotations
import sys, time, re
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
GENOMES  = ANALYSIS / "genomes_full"
SCOARY   = ANALYSIS / "scoary_full"; SCOARY.mkdir(exist_ok=True)
FIG      = ANALYSIS / "figures"; FIG.mkdir(exist_ok=True)
WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

GPA_CSV  = ANALYSIS / "roary_full" / "out" / "gene_presence_absence.csv"
assert GPA_CSV.exists(), f"Missing Roary output: {GPA_CSV}"

# ── 1. Build phenotype matrix ───────────────────────────────────────────────
samples = sorted(p.stem for p in GENOMES.glob("*.fna"))
species_of: dict[str, str] = {}
for s in samples:
    with (GENOMES / f"{s}.fna").open() as fh: hdr = fh.readline()
    m = re.search(r"Dickeya\s+([A-Za-z]+)", hdr)
    species_of[s] = m.group(1) if m else "unknown"

VW_SET = {"dianthicola", "solani", "dadantii", "fangzhongdai",
          "chrysanthemi", "undicola"}
SR_SET = {"zeae", "oryzae", "ananatis", "parazeae"}

traits_csv = SCOARY / "traits.csv"
traits_csv.write_text(
    "Name,vascular_wilt,soft_rot,is_solani,is_dianthicola\n" +
    "\n".join(
        f"{s},"
        f"{int(species_of[s] in VW_SET)},"
        f"{int(species_of[s] in SR_SET)},"
        f"{int(species_of[s] == 'solani')},"
        f"{int(species_of[s] == 'dianthicola')}"
        for s in samples
    ) + "\n",
    encoding="utf-8",
)

n_pos = {
    "vascular_wilt":   sum(1 for s in samples if species_of[s] in VW_SET),
    "soft_rot":        sum(1 for s in samples if species_of[s] in SR_SET),
    "is_solani":       sum(1 for s in samples if species_of[s] == "solani"),
    "is_dianthicola":  sum(1 for s in samples if species_of[s] == "dianthicola"),
}
for k, v in n_pos.items():
    print(f"  {k:<18s} positives={v:3d}  negatives={len(samples)-v:3d}")

# ── 2. Roary's gene_presence_absence.csv has /work/-prefixed paths in
# its header (sample names are the GFF basenames, which match our IDs) ──
# Scoary needs sample-IDs in the GPA matching the traits.csv first column.
# Roary stores them as the Prokka prefix used at GFF-stage time, which is
# our accession (GCF_xxxx.x).  Verify alignment.
import pandas as pd
gpa = pd.read_csv(GPA_CSV, low_memory=False)
gpa_samples = set(gpa.columns) - {
    "Gene", "Non-unique Gene name", "Annotation", "No. isolates",
    "No. sequences", "Avg sequences per isolate", "Genome Fragment",
    "Order within Fragment", "Accessory Fragment", "Accessory Order with Fragment",
    "QC", "Min group size nuc", "Max group size nuc", "Avg group size nuc",
}
overlap = gpa_samples & set(samples)
print(f"\nGPA columns: {len(gpa.columns)}  matched-to-traits samples: {len(overlap)}/{len(samples)}")
if len(overlap) < len(samples):
    missing = set(samples) - gpa_samples
    print(f"  missing in GPA: {len(missing)} (showing 5): {list(missing)[:5]}")

# ── 3. Run Scoary ───────────────────────────────────────────────────────────
print("\nRunning Scoary on 262-genome pangenome ...")
t0 = time.time()
r = backend.run(
    image="quay.io/biocontainers/scoary:1.6.16--py_2",
    command=(
        f"sh -c 'cd {WS_CTR}/scoary_full && "
        f"scoary -t traits.csv "
        f"-g {WS_CTR}/roary_full/out/gene_presence_absence.csv "
        f"--no_pairwise --no-time -o results --threads 4'"
    ),
    mounts={WS_HOST: WS_CTR}, cpu=4, ram_gb=8, workdir=WS_CTR,
)
print(f"  exit={r.exit_code}  elapsed={(time.time()-t0)/60:.1f}m")
if r.exit_code != 0:
    print((r.stderr or r.stdout)[-2000:]); sys.exit(1)

# ── 4. Visualise & summarise per trait ─────────────────────────────────────
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

results_dir = SCOARY / "results"
csvs = sorted(results_dir.glob("*.csv"))
print(f"\nScoary outputs: {[p.name for p in csvs]}")

for csv in csvs:
    if "vascular_wilt"   in csv.name: trait = "vascular_wilt"
    elif "soft_rot"      in csv.name: trait = "soft_rot"
    elif "is_solani"     in csv.name: trait = "is_solani"
    elif "is_dianthicola" in csv.name: trait = "is_dianthicola"
    else: continue

    df = pd.read_csv(csv)
    # With n=262, Bonferroni is now genuinely useful
    sig = df[df["Bonferroni_p"] < 0.05].sort_values("Bonferroni_p").head(30)
    if sig.empty:
        print(f"  {trait:<18s}: no Bonferroni-significant hits (rare)")
        continue
    print(f"  {trait:<18s}: {len(df):,} candidate genes  /  "
          f"{(df['Bonferroni_p']<0.05).sum():,} Bonferroni-sig")

    sig["log10p"] = -np.log10(sig["Bonferroni_p"].clip(lower=1e-300))
    fig, ax = plt.subplots(figsize=(10, max(4, 0.3*len(sig))), dpi=130)
    bars = ax.barh(
        sig["Gene"][::-1], sig["log10p"][::-1],
        color=["#d62728" if r.Sensitivity > 80 and r.Specificity > 80
               else "#ff7f0e" if r.Sensitivity > 80 or r.Specificity > 80
               else "#1f77b4"
               for r in sig.iloc[::-1].itertuples()],
    )
    ax.set_xlabel("-log10(Bonferroni p)")
    ax.set_title(
        f"Scoary GWAS (262 genomes): top genes for {trait}\n"
        f"red = sens & spec > 80%   orange = one > 80%   blue = both ≤ 80%"
    )
    plt.tight_layout()
    plt.savefig(FIG / f"scoary_full_{trait}.png"); plt.close()

    sig[["Gene", "Annotation", "Naive_p", "Bonferroni_p",
         "Sensitivity", "Specificity", "Odds_ratio"]].to_csv(
        SCOARY / f"top30_{trait}.tsv", sep="\t", index=False,
    )

print("\nScoary GWAS complete.")
