"""Build the final consolidated HTML report for the Dickeya analysis."""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parent
ROARY_STATS = (ROOT / "roary" / "out" / "summary_statistics.txt").read_text(encoding="utf-8")
buckets = {}
for line in ROARY_STATS.strip().splitlines():
    parts = line.split("\t")
    if len(parts) >= 3 and parts[0].lower() != "total genes":
        buckets[parts[0]] = int(parts[-1])
total = sum(buckets.values())

# Loose-Roary stats (where available)
LOOSE_STATS = ROOT / "roary" / "out_loose" / "summary_statistics.txt"
buckets_loose = {}
if LOOSE_STATS.exists():
    for line in LOOSE_STATS.read_text(encoding="utf-8").strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].lower() != "total genes":
            buckets_loose[parts[0]] = int(parts[-1])

# Full FastANI species-range table (262 genomes)
FULL_LOG = ROOT / "full_ani.log"
species_ranges_block = ""
if FULL_LOG.exists():
    log_text = FULL_LOG.read_text(encoding="utf-8")
    after = log_text.split("Within-species ANI ranges:", 1)
    if len(after) == 2:
        rows = []
        for line in after[1].strip().splitlines():
            line = line.strip()
            if not line or "Done" in line: continue
            rows.append(f"<tr><td><code>D. {line}</code></td></tr>")
        if rows:
            species_ranges_block = (
                "<table><tr><th>262-genome species ANI ranges</th></tr>"
                + "".join(rows) + "</table>"
            )

# Scoary top hits per phenotype
def _scoary_top(phenotype: str, n: int = 10) -> str:
    p = ROOT / "scoary" / f"top25_{phenotype}.tsv"
    if not p.exists(): return ""
    import pandas as pd
    df = pd.read_csv(p, sep="\t").head(n)
    return "<table><tr><th>gene</th><th>annotation</th><th>sens%</th><th>spec%</th></tr>" + "".join(
        f"<tr><td><code>{r.Gene}</code></td>"
        f"<td>{(r.Annotation or '')[:60]}</td>"
        f"<td>{int(r.Sensitivity)}</td><td>{int(r.Specificity)}</td></tr>"
        for r in df.itertuples()
    ) + "</table>"


scoary_vw = _scoary_top("vascular_wilt")
scoary_sr = _scoary_top("soft_rot")


def _scoary_full_top(phenotype: str, n: int = 12) -> str:
    p = ROOT / "scoary_full" / f"top30_{phenotype}.tsv"
    if not p.exists(): return ""
    import pandas as pd
    df = pd.read_csv(p, sep="\t").head(n)
    return ("<table><tr><th>gene</th><th>annotation</th>"
            "<th>Bonf p</th><th>sens%</th><th>spec%</th></tr>" + "".join(
        f"<tr><td><code>{r.Gene}</code></td>"
        f"<td>{(r.Annotation or '')[:55]}</td>"
        f"<td>{r.Bonferroni_p:.1e}</td>"
        f"<td>{int(r.Sensitivity)}</td><td>{int(r.Specificity)}</td></tr>"
        for r in df.itertuples()
    ) + "</table>")


# 262-genome Scoary hit counts
scoary_full_counts = {}
for trait in ("vascular_wilt", "soft_rot", "is_solani", "is_dianthicola"):
    f = ROOT / "scoary_full" / "results" / f"{trait}.results.csv"
    if f.exists():
        import pandas as pd
        df = pd.read_csv(f)
        scoary_full_counts[trait] = (
            len(df), int((df["Bonferroni_p"] < 0.05).sum()),
        )
# Per-trait positive counts (read from the full scoary traits.csv)
n_pos: dict[str, int] = {}
traits_full = ROOT / "scoary_full" / "traits.csv"
if traits_full.exists():
    import pandas as pd
    tdf = pd.read_csv(traits_full)
    for col in tdf.columns[1:]:
        n_pos[col] = int(tdf[col].sum())

scoary_full_vw = _scoary_full_top("vascular_wilt")
scoary_full_sr = _scoary_full_top("soft_rot")
scoary_full_so = _scoary_full_top("is_solani")
scoary_full_di = _scoary_full_top("is_dianthicola")

# 262-genome full Roary results (if present)
FULL_PG = ROOT / "roary_full" / "out" / "summary_statistics.txt"
buckets_full = {}
if FULL_PG.exists():
    for line in FULL_PG.read_text(encoding="utf-8").strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].lower() != "total genes":
            buckets_full[parts[0]] = int(parts[-1])
total_full = sum(buckets_full.values())

# Per-genome AMR/VF counts
ABR = ROOT / "abricate"
samples = sorted(p.stem.rsplit(".vfdb", 1)[0]
                 for p in ABR.glob("*.vfdb.tsv"))
DBS = ["vfdb", "card", "plasmidfinder"]
amr_rows = []
for s in samples:
    short = "_".join(s.split("_")[:2])
    counts = []
    for db in DBS:
        f = ABR / f"{s}.{db}.tsv"
        n = max(sum(1 for _ in f.open()) - 1, 0) if f.exists() else 0
        counts.append(n)
    amr_rows.append((short, counts))

amr_table = "<table><tr><th>genome</th>" + \
    "".join(f"<th>{db}</th>" for db in DBS) + "</tr>" + \
    "".join(
        f"<tr><td>{n}</td>" + "".join(f"<td>{c}</td>" for c in cs) + "</tr>"
        for n, cs in amr_rows
    ) + "</table>"

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Dickeya genus comparative genomics</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 1150px;
        margin: 2em auto; color:#222; padding: 0 20px }}
 h1 {{ border-bottom: 2px solid #1f3a93; padding-bottom: 4px; color: #1f3a93 }}
 h2 {{ color: #1f3a93; margin-top: 1.5em }}
 .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px }}
 .card {{ border:1px solid #ddd; border-radius:8px; padding:16px; background:#fafafa }}
 img  {{ max-width: 100%; height: auto; display:block; margin:10px auto }}
 table {{ border-collapse: collapse; margin: 8px 0; font-size: 0.9em }}
 th, td {{ padding: 4px 10px; border-bottom: 1px solid #ddd; text-align: left }}
 th {{ background: #eee }}
 .muted {{ color: #666; font-size: 0.85em }}
 .key {{ background:#f0f6ff; border-left:4px solid #1f3a93; padding:8px 14px; margin:12px 0 }}
</style></head><body>
<h1>Dickeya — comparative genomics</h1>
<p class="muted">13 NCBI RefSeq reference genomes (one per recognised species).
   Annotated with Prokka v1.14.6 · ANI by FastANI v1.34 · pangenome by Roary v3.13 ·
   ML phylogeny by IQ-TREE v2.2.2.7 · UPGMA from ANI distances · resistome/virulome by ABRicate v1.2.</p>

<div class="key">
<b>Headline findings.</b>
ANI separates the genus into water-associated <i>D. aquatica</i> / <i>D. lacustris</i>
basal pair, a "vascular wilt" clade (<i>solani / dadantii / fangzhongdai / dianthicola / undicola / chrysanthemi</i>),
and a "soft rot" clade (<i>zeae / parazeae / oryzae / ananatis</i>).
The pangenome is wide-open: only {buckets_full.get('Core genes', buckets.get('Core genes',0))}
genes are core across the entire genus (262 strains), while the
pan-genome reaches {total_full:,} clusters and is still climbing
even at n=262.
Acquired antibiotic resistance is essentially absent (CARD finds the
universally-present regulator CRP only); virulence repertoire (T6SS, flagella,
iron uptake) is concentrated in the clinically aggressive clades.
</div>

<h2>1 · Pairwise ANI</h2>
<div class="card">
<img src="figures/ani_heatmap.png" alt="ANI heatmap">
<p class="muted">Hierarchical clustering of all 13 vs 13 ANI values. The 95% species threshold
clearly separates the four soft-rot members (94-96% within-clade ANI) from everything else.</p>
</div>

<h2>2 · Phylogeny</h2>
<div class="grid">
  <div class="card">
    <h3>UPGMA from ANI</h3>
    <img src="figures/tree_ani_nj.png" alt="ANI tree">
    <p class="muted">Whole-genome relatedness; recovers the soft-rot and vascular-wilt clades.</p>
  </div>
  <div class="card">
    <h3>ML — IQ-TREE</h3>
    <img src="figures/tree_ml_iqtree.png" alt="ML tree">
    <p class="muted"><b>Caveat:</b> Roary's MAFFT-mode core alignment was only 498 bp here
       (most of the 608 core gene families failed to align cleanly across the
       distantly-related species). The ML tree is therefore poorly resolved at deep nodes —
       the ANI tree is the more reliable species-level summary for this genus.</p>
  </div>
</div>

<h2>3 · Pangenome</h2>
<div class="grid">
  <div class="card">
    <img src="figures/pangenome_pie.png" alt="pangenome composition">
    <table>
      {''.join(f'<tr><td>{k}</td><td>{v:,}</td></tr>' for k,v in buckets.items())}
      <tr><td><b>Total</b></td><td><b>{total:,}</b></td></tr>
    </table>
  </div>
  <div class="card">
    <img src="figures/pangenome_curve.png" alt="rarefaction">
    <p class="muted">Open pangenome — pan-genome continues to grow with each added genome.</p>
  </div>
</div>

<h2>4 · Virulence factors (VFDB)</h2>
<div class="card">
<img src="figures/abricate_vfdb.png" alt="VFDB heatmap">
<p>The <b>Type 6 Secretion System (T6SS)</b> components <code>hcp1 / hcp / vipB</code>,
the <b>flagellar motor switch</b> <code>fliG</code>, the <b>iron-uptake regulator</b> <code>fur</code>,
and the <b>stress-response sigma factor</b> <code>rpoS</code> are conserved across the
clinically relevant clades. <i>D. aquatica</i> / <i>D. lacustris</i> / <i>D. poaceiphila</i>
carry only 1-3 of these, consistent with their less aggressive plant-pathogenic
phenotypes.</p>
</div>

<h2>5 · Antimicrobial resistance (CARD) and plasmids</h2>
<div class="grid">
  <div class="card">
    <h3>CARD — acquired AMR</h3>
    <img src="figures/abricate_card.png" alt="CARD heatmap">
    <p class="muted">Only the universally-present regulator <code>CRP</code> is detected.
       Dickeya is a plant pathogen, not a clinical isolate — there is essentially
       <b>no acquired antibiotic resistance burden</b> in the genus.</p>
  </div>
  <div class="card">
    <h3>Per-genome counts</h3>
    {amr_table}
  </div>
</div>

<h2>6 · Phenotype-associated genes (Scoary GWAS)</h2>
<p>Phenotypes derived from ANI clade membership (binary). Top-10 hits with
   sensitivity & specificity ≥ 80% shown.</p>
<div class="grid">
  <div class="card">
    <h3>Vascular wilt clade (n=6)</h3>
    <img src="figures/scoary_vascular_wilt.png" alt="vw scoary">
    {scoary_vw}
    <p class="muted">Top hits include the known Dickeya virulence factors
    <code>prtC</code> (Zn-metalloprotease) and <code>pemB</code>
    (pectin methylesterase) — enzymes that degrade plant cell walls.</p>
  </div>
  <div class="card">
    <h3>Soft-rot clade (n=4)</h3>
    <img src="figures/scoary_soft_rot.png" alt="sr scoary">
    {scoary_sr}
    <p class="muted">Soft-rot accessory genes are enriched for
    <code>cdiA</code> (contact-dependent inhibition toxin),
    <code>fixA/B/X</code> (nitrogen fixation, anaerobic adaptation),
    <code>fadK</code> (fatty-acid metabolism) — competition and
    environmental-tolerance traits rather than direct virulence.</p>
  </div>
</div>

<h2>6b · Genus-scale Scoary GWAS (n=262, Bonferroni-significant)</h2>
<div class="key">
With 262 genomes the GWAS escapes the small-sample plateau seen at n=13:
significance now reaches Bonferroni p ≈ 10<sup>-47</sup> to 10<sup>-67</sup>,
and we recover textbook plant-pathogen virulence machinery in coordinated
operons rather than as one-off hits.
</div>

<table>
  <tr><th>Phenotype</th><th>positives</th><th>candidate genes</th><th>Bonferroni-sig (p&lt;0.05)</th></tr>
  {''.join(
      f'<tr><td>{t}</td><td>{n_pos[t]}</td><td>{c[0]:,}</td><td>{c[1]:,}</td></tr>'
      for t, c in scoary_full_counts.items()
  ) if scoary_full_counts else '<tr><td colspan=4>no results</td></tr>'}
</table>

<div class="grid">
  <div class="card">
    <h3>vascular_wilt (n=202)</h3>
    <img src="figures/scoary_full_vascular_wilt.png" alt="vw scoary 262">
    {scoary_full_vw}
    <p class="muted"><b>Coordinated virulence module:</b> Type II Secretion
    System (<code>xcpW</code>, <code>outS</code>) + minor endoglucanase
    <code>celY</code> + the full SUF Fe-S cluster assembly operon
    (<code>sufA/B/D/E</code>) + iron-acquisition (<code>fepB</code>,
    <code>sbnE</code>) + outer-membrane integrity
    (<code>eptB</code>, <code>dsbD</code>).  This is the canonical
    plant-cell-wall-degrading + secretion machinery of soft-rot
    Pectobacteriaceae.</p>
  </div>
  <div class="card">
    <h3>soft_rot (n=46)</h3>
    <img src="figures/scoary_full_soft_rot.png" alt="sr scoary 262">
    {scoary_full_sr}
    <p class="muted"><b>Negative signal of note:</b> <code>hflK</code>
    (FtsH protease modulator) sensitivity = 0% — i.e. the gene is
    <i>missing</i> in soft-rot strains while present elsewhere.  Other top
    hits are clade-specific accessory clusters not yet annotated.</p>
  </div>
  <div class="card">
    <h3>is_solani (n=51)</h3>
    <img src="figures/scoary_full_is_solani.png" alt="solani scoary 262">
    {scoary_full_so}
    <p class="muted">Top hits include <code>dosP</code> (c-di-GMP
    phosphodiesterase, biofilm regulation), <code>AbaF</code>
    (fosfomycin-resistance efflux pump — the genus's only meaningful AMR
    signal), <code>XynC</code> (glucuronoxylanase, plant cell wall
    degradation) and <code>TatB</code> (Sec-independent secretion).
    Identical-p<sub>Bonf</sub> tied genes share the same presence/absence
    vector but, as section 8 shows, are scattered across the chromosome
    rather than co-located — except for one genuine 5-gene operon
    around <code>AbaF</code>.</p>
  </div>
  <div class="card">
    <h3>is_dianthicola (n=87)</h3>
    {scoary_full_di}
    <p class="muted">Strongest signal in the dataset (Bonferroni
    p ≈ 10<sup>-67</sup>).  Highlights: <code>cusR</code> (copper sensing
    regulator → host metal-stress adaptation), bifunctional cytochrome
    P450/NADPH reductase, <code>aaeA</code> efflux pump,
    <code>glnQ</code> (glutamine transport).  Profile consistent with
    the hardened metabolic envelope of an aggressive carnation pathogen.</p>
  </div>
</div>

<h2>7a · 262-genome genus-wide pangenome (Roary)</h2>
<div class="grid">
  <div class="card">
    <img src="figures/pangenome_full_pie.png" alt="full pangenome composition">
    <table>
      {''.join(f'<tr><td>{k}</td><td>{v:,}</td></tr>' for k,v in buckets_full.items())}
      <tr><td><b>Total clusters</b></td><td><b>{total_full:,}</b></td></tr>
    </table>
  </div>
  <div class="card">
    <img src="figures/pangenome_full_curve.png" alt="full rarefaction">
    <p class="muted">Pan-genome still climbing at n=262 — Dickeya genus is
    a strongly <b>open</b> pangenome.  Core stabilises near
    {buckets_full.get('Core genes', '?')} genes from ~30 strains onward,
    confirming the 13-genome estimate ({buckets.get('Core genes','?')})
    was already close to the true genus core.</p>
    <p class="muted">Compared to the 13-genome run: core barely changed
    (+13%) while cloud genes grew +72% to {buckets_full.get('Cloud genes','?'):,}
    — every new strain still contributes unique accessory content.</p>
  </div>
</div>

<h2>7b · 262-genome subspecies-level ANI</h2>
<div class="card">
<img src="figures/ani_full_heatmap.png" alt="full ANI heatmap">
<p>All 262 GCF (RefSeq) Dickeya assemblies, FastANI all-vs-all (≈70k pairs).
   Each row/col is a single assembly; the colour stripe on the left marks
   species. Yellow squares (≥97% ANI) recover textbook-clean species
   clusters with two interesting outliers:</p>
<ul>
  <li><i>D. zeae</i> (n=22) spans <b>94.4-100% ANI</b> — straddles the
      95% species threshold, suggesting at least one cryptic species
      hides inside the current "zeae" label.</li>
  <li><i>D. sp.</i> unassigned (n=7) ranges <b>81.7-99.9%</b> — these
      likely include genuinely novel species awaiting formal description.</li>
</ul>
{species_ranges_block}
</div>

<h2>8 · D. solani AbaF mini-cluster — closer look at one Scoary hit</h2>
<div class="card">
<p>The 30 top is_solani Scoary hits all share the same presence/absence
vector (every solani strain has them, every other species lacks them) and
therefore tie at p<sub>Bonf</sub> ≈ 4.5 × 10<sup>-51</sup>.  When we map
those locus tags back to the type-strain GFF (<code>GCF_001644705.1</code>,
<i>D. solani</i> IPO 2222), the 30 genes turn out to be <b>scattered across
4.17 Mb of the chromosome</b> — not a single inherited island.</p>
<p>Five of them, however, are co-located in a tight ~5 kb operon-style
block at <b>4.195-4.200 Mb</b>:</p>
<table>
<tr><th>locus</th><th>strand</th><th>position</th><th>annotation</th></tr>
<tr><td><code>abaF_2</code></td><td>-</td><td>4,195,388-4,196,701</td><td>Fosfomycin-resistance MFS efflux pump</td></tr>
<tr><td><code>DNMKAHCA_03629</code></td><td>-</td><td>4,196,694-4,197,329</td><td>hypothetical</td></tr>
<tr><td><code>cnbH</code></td><td>-</td><td>4,197,332-4,198,675</td><td>2-amino-5-chloromuconic acid deaminase</td></tr>
<tr><td><code>DNMKAHCA_03631</code></td><td>-</td><td>4,198,686-4,199,366</td><td>hypothetical</td></tr>
<tr><td><code>rspR_2</code></td><td>+</td><td>4,199,480-4,200,154</td><td>HTH-type transcriptional repressor RspR</td></tr>
</table>

<div class="grid">
  <div class="card">
    <h3>Synteny — 5 representative D. solani strains</h3>
    <img src="figures/solani_island_synteny.png" alt="synteny">
    <p class="muted">Gene order, spacing and relative orientation
    are perfectly preserved; only the chromosomal coordinate origin
    differs (artefact of how each assembly was rotated when circularised).</p>
  </div>
  <div class="card">
    <h3>GC content track</h3>
    <img src="figures/solani_island_gc.png" alt="GC track">
    <p class="muted">Cluster GC% = <b>52.82%</b>, vs whole-chromosome
    mean 56.24% — a 3.42-point dip at the <b>18th percentile</b> of all
    5 kb windows.  Lower-than-host GC is a classical fingerprint of
    horizontal acquisition.</p>
  </div>
</div>

<h3>Mobile-element evidence summary</h3>
<table>
<tr><th>signal</th><th>finding</th><th>verdict</th></tr>
<tr><td>operon-style gene order</td><td>5/5 strains preserved</td><td>✓ inherited as a unit</td></tr>
<tr><td>GC% deviation</td><td>-3.4% from genome mean (18th %ile)</td><td>✓ HGT-suggestive</td></tr>
<tr><td>tRNA flanking</td><td><code>tRNA-Pro(ggg)</code> at 4,204,505 — 4.4 kb downstream</td><td>✓ classic integration target</td></tr>
<tr><td>transposase / integrase / IS / phage in ±10 kb</td><td>none detected</td><td>✗ direct mobility marker missing</td></tr>
<tr><td>flanking direct repeats</td><td>not assessed</td><td>?</td></tr>
</table>
<p class="muted">Best-fit model: an <b>ancient horizontal acquisition</b>
that integrated near the tRNA-Pro and was subsequently fixed in the
<i>D. solani</i> lineage; the mobilising element itself has eroded over
time, leaving the tRNA-Pro hotspot and atypical GC% as the only
remaining footprints.  The cargo — a fosfomycin-resistance efflux pump
flanked by an aromatic-amine deaminase and an HTH regulator — looks
like a <b>xenobiotic-detoxification cassette</b>, plausibly an
adaptation to soil/rhizosphere antimicrobial pressure.</p>
</div>

<h2>8b · 262-strain ML phylogeny + virulome heatmap</h2>
<div class="card">
<img src="figures/tree_full_with_vfdb.png" alt="262-strain ML tree with VFDB" style="max-height:1200px">
<p class="muted"><b>Custom 50-gene supermatrix.</b>  Roary's full
pan-genome run was performed without <code>-e -n</code>, so we built our
own concatenated alignment: 50 single-copy core genes (≥99% strain
prevalence, exactly one copy per strain), each MAFFT-aligned in parallel
inside a container, then concatenated to a <b>91,756 bp × 262 strain</b>
supermatrix.  IQ-TREE 2 GTR+G with 1000 ultrafast bootstrap completed in
<b>17 minutes</b> on 4 CPU.  Best ML log-likelihood = -668,525.</p>
<p class="muted"><b>Tree-VFDB alignment.</b>  Each leaf's species is
shown by the color strip; the heatmap on the right encodes presence of
the 15 most prevalent VFDB genes across all 262 genomes.  Two
biological observations:</p>
<ol>
<li>Each named species forms a tight monophyletic clade — nominal
    species labels survive a real ML test on the genus.</li>
<li>The basal water-associated clade (<i>D. aquatica / lacustris /
    poaceiphila</i> at the bottom) carries almost none of the T6SS
    machinery (<code>hcp1, vipB, hcp, tssJ/F/M/clpV</code>),
    confirming that virulence build-up post-dates the
    environmental-to-pathogen transition in the genus.</li>
</ol>
</div>

<h2>8c · Genus-wide AMR + virulome + plasmid catalogue (262 genomes)</h2>
<table>
<tr><th>database</th><th>unique genes</th><th>total hits</th><th>per-genome mean ± sd</th></tr>
<tr><td>VFDB</td><td>20</td><td>2,252</td><td>8.6 ± 2.2</td></tr>
<tr><td>CARD</td><td>6</td><td>267</td><td>1.0 ± 0.2 (= CRP only)</td></tr>
<tr><td>PlasmidFinder</td><td>7</td><td>21</td><td>0.1 ± 0.4</td></tr>
</table>

<div class="grid">
  <div class="card">
    <h3>VFDB prevalence by species</h3>
    <img src="figures/abricate_full_vfdb.png" alt="VFDB heatmap full">
    <p class="muted">T6SS core (<code>cheY, rcsB, rpoS, vipB, hcp1</code>),
    flagella (<code>fliG, atsL</code>), iron uptake (<code>fur</code>) are
    100% conserved across the agriculturally-aggressive species; in the
    water-associated clade (<i>aquatica, lacustris, poaceiphila</i>) they
    are essentially absent.</p>
  </div>
  <div class="card">
    <h3>Per-genome hits by species</h3>
    <img src="figures/abricate_full_boxplot.png" alt="boxplot">
    <p class="muted">Median VFDB hits cluster at 8-11 in the pathogenic
    clades versus 1-3 in the water-associated lineage — a 5-10× gap that
    is itself a hallmark of the host-tropism transition.  CARD remains
    flat at 1 (CRP), PlasmidFinder is sporadic with <i>D. undicola</i>
    as the only consistent plasmid carrier.</p>
  </div>
</div>

<h2>8d · CAFE5 ancestral state reconstruction — when did virulence
genes appear / disappear?</h2>
<p>The 262-strain ML tree was rendered ultrametric (extend-tip
method, every leaf equidistant from the root), and a 20-row VFDB count
matrix (per-genome copy numbers from ABRicate) was fed to <b>CAFE5
v5.1</b> with default birth-death model.  CAFE estimated a single
genus-wide gene-family birth/death rate λ = 1.28 × 10<sup>-3</sup>
events / branch / family (–lnL = 1089.34) and computed per-branch
ancestral counts.</p>

<div class="key">
<b>Headline.</b>  Of 20 VFDB families, <b>only two — <code>hcp</code>
and <code>hcp1</code> — show a non-random rate (CAFE p &lt; 0.05)</b>.
Both are core components of the <b>Type VI Secretion System</b> (T6SS)
injection apparatus.  Every other VFDB family's count distribution is
explained by the null constant-rate model, i.e. their gain/loss occurs
at the genus-wide background pace.
</div>

<table>
<tr><th>family</th><th>annotation</th><th>CAFE p</th><th>verdict</th></tr>
<tr><td><code>hcp</code></td><td>T6SS Hcp tube protein</td><td>0.005</td><td>★ non-random</td></tr>
<tr><td><code>hcp1</code></td><td>T6SS Hcp tube paralog</td><td>≈ 0</td><td>★ non-random</td></tr>
<tr><td>vipB</td><td>T6SS contractile sheath</td><td>0.964</td><td>random</td></tr>
<tr><td>cheY/rcsB/rpoS/fur/atsL/fliG/...</td><td>regulators · iron · flagella</td><td>0.95-0.98</td><td>random</td></tr>
</table>

<div class="grid">
  <div class="card">
    <h3>Tree-level gain/loss (all families)</h3>
    <img src="figures/cafe_vfdb_tree.png" alt="CAFE tree">
    <p class="muted">Branches red where CAFE infers expansion, blue
    where it infers contraction.  Most dynamism is concentrated in the
    upper <i>D. dianthicola</i> clade and the basal water-associated
    lineage at the bottom — the latter shows the T6SS loss event that
    set up the genus's environmental sub-clade.</p>
  </div>
  <div class="card">
    <h3>Significant T6SS families — copy number by species</h3>
    <img src="figures/cafe_hcp_detail.png" alt="hcp detail">
    <p class="muted"><code>hcp1</code>: 1.5-2.5 copies in pathogenic
    clades, 0 in <i>aquatica / lacustris / poaceiphila</i>.
    <code>hcp</code>: 0.5-1 copies in pathogens, 0 in environmentals.
    Together they reveal a <b>T6SS expansion event</b> on the stem
    branch leading to the agricultural-pathogen clades, with subsequent
    paralog duplication in the high-virulence lineages.</p>
  </div>
</div>

<p class="muted">Biological reading: <b>T6SS is the single most
phylogenetically dynamic virulence module in the genus</b>, undergoing
both expansion (in the pathogen lineage) and complete loss (in the
environmental water-associated lineage).  All other queried VFDB
factors — global regulators, iron homeostasis, flagella — are
pan-genus housekeeping that CAFE correctly identifies as evolving at
background rate.  This recapitulates from a phylogenetic-model angle
what we already saw at the descriptive level (sections 4, 8c) and at
the GWAS level (section 6b): T6SS is the molecular signature that
separates plant pathogens from environmental opportunists in
<i>Dickeya</i>.</p>

<h2>9 · Pangenome functional categories (COG-2024)</h2>
<p>Pangenome representatives (one protein per Roary cluster, 34,629 total)
were searched against COG-2024 with DIAMOND blastp (≥1e-5, very-sensitive).
Each best-hit COG was mapped to its functional-category letter via
<code>cog-24.def.tab</code>; multi-letter assignments were exploded.</p>

<table>
  <tr><th>bucket</th><th>n clusters</th><th>% mapped to COG</th></tr>
  <tr><td>core</td><td>687</td><td>79.8%</td></tr>
  <tr><td>soft_core</td><td>676</td><td>61.4%</td></tr>
  <tr><td>shell</td><td>5,247</td><td>45.6%</td></tr>
  <tr><td>cloud</td><td>28,019</td><td><b>27.9%</b> (the rest = unclassifiable accessory dark matter)</td></tr>
</table>

<div class="grid">
  <div class="card">
    <h3>Functional composition</h3>
    <img src="figures/cog_stacked.png" alt="cog stacked">
    <p class="muted">Translation/ribosome (J) dominates the core (16.6%)
    and shrinks to 3.9% in the cloud — the canonical signature of essential
    machinery being conserved.</p>
  </div>
  <div class="card">
    <h3>Cloud-vs-core enrichment</h3>
    <img src="figures/cog_delta.png" alt="cog delta">
    <p class="muted">Categories that dominate one bucket but not the other,
    in percentage points.  Red = enriched in cloud, blue = enriched in core.</p>
  </div>
</div>

<div class="key">
<b>Headline finding.</b>  The single biggest cloud-enrichment is COG
category <b>X (Mobilome — phage / IS / transposons)</b>: 0% of core
proteins, but <b>8.6% of cloud proteins</b>.  This explains
mechanistically why the pan-genome stays open at n=262 — most accessory
content is either currently mobile DNA or recently arrived through it.
Other cloud-enriched categories (L replication/repair, V defense,
Q secondary metabolites) are exactly what one expects to ride mobile
genetic elements.  The mirror-image core-enrichment in J translation
and E amino-acid metabolism shows that the conserved 687 genes are
overwhelmingly housekeeping.
</div>

<h3>Top cloud-enriched COG categories</h3>
<table>
<tr><th>cat</th><th>core %</th><th>cloud %</th><th>Δpp</th><th>description</th></tr>
<tr><td>X</td><td>0.00</td><td>8.64</td><td>+8.64</td><td><b>Mobilome (phage/IS)</b></td></tr>
<tr><td>R</td><td>1.80</td><td>6.71</td><td>+4.90</td><td>General prediction only</td></tr>
<tr><td>L</td><td>2.95</td><td>6.85</td><td>+3.90</td><td>Replication/repair</td></tr>
<tr><td>Q</td><td>1.15</td><td>4.55</td><td>+3.41</td><td>Secondary metabolites</td></tr>
<tr><td>V</td><td>1.64</td><td>4.15</td><td>+2.51</td><td>Defense mechanisms</td></tr>
</table>
<h3>Top core-enriched (= cloud-depleted)</h3>
<table>
<tr><th>cat</th><th>core %</th><th>cloud %</th><th>Δpp</th><th>description</th></tr>
<tr><td>J</td><td>16.56</td><td>3.93</td><td>-12.63</td><td><b>Translation/ribosome</b></td></tr>
<tr><td>E</td><td>11.97</td><td>7.45</td><td>-4.52</td><td>Amino acid metabolism</td></tr>
<tr><td>K</td><td>7.38</td><td>4.51</td><td>-2.87</td><td>Transcription</td></tr>
<tr><td>F</td><td>4.43</td><td>1.88</td><td>-2.54</td><td>Nucleotide metabolism</td></tr>
</table>

<p class="muted">This corroborates the AbaF mini-cluster finding from
section 8: when we zoom into one specific Scoary hit we find
xenobiotic-detoxification cargo near a tRNA integration hotspot with
atypical GC%; when we zoom out to the whole pangenome we find the same
mechanism (mobile DNA) is the dominant driver of accessory diversity
across the entire genus.</p>

<h2>10 · Methods</h2>
<ol>
  <li><b>Genome retrieval.</b> <code>bioflow ncbi genome --taxon dickeya
   --reference-only --include GENOME_FASTA,GENOME_GFF</code> — 13 RefSeq reference assemblies.</li>
  <li><b>Re-annotation.</b> Prokka 1.14.6, <code>--kingdom Bacteria --genus Dickeya --usegenus</code>,
   parallel x4 via bioflow's DockerBackend.</li>
  <li><b>ANI.</b> FastANI 1.34 all-vs-all on raw FASTA.</li>
  <li><b>Pangenome.</b> Roary 3.13 with <code>-e -n -v</code>, default 95% identity,
   13 input GFFs.</li>
  <li><b>Phylogeny.</b> IQ-TREE 2 ModelFinder + 1000 ultrafast bootstrap on Roary's
   core_gene_alignment.aln; supplementary UPGMA of (100-ANI)/2 distances via
   scipy.cluster.hierarchy.</li>
  <li><b>Resistome / virulome.</b> ABRicate 1.2 against VFDB, CARD, PlasmidFinder
   (default thresholds: 80% identity, 80% coverage minimum).</li>
  <li><b>Pangenome-wide GWAS.</b> Roary re-run with <code>-i 70</code>
   ({buckets_loose.get('Core genes', '?')} core genes from a richer
   {sum(buckets_loose.values()) or '?'}-cluster pangenome) feeding
   Scoary 1.6.16 binary-trait analysis on vascular_wilt vs others
   (n=6/13) and soft_rot vs others (n=4/13).</li>
  <li><b>Subspecies ANI expansion.</b> All 262 GCF Dickeya assemblies
   downloaded via batched NCBI Datasets v2 calls (HTTP 414 workaround
   patched into bioflow), FastANI all-vs-all in a single container.</li>
  <li><b>262-strain ML phylogeny.</b> 50 single-copy core genes from
   the Roary cluster table, MAFFT-aligned independently inside a
   <code>staphb/mafft:7.520</code> container (8 parallel × 1 cpu),
   concatenated to a 91,756 bp supermatrix; IQ-TREE 2 (<code>-m GTR+G
   -bb 1000 -nt 4</code>) on the supermatrix, 17 min wall.</li>
  <li><b>Genus-wide ABRicate.</b> 786 runs (262 × 3 DBs: VFDB, CARD,
   PlasmidFinder), 12 parallel × 1 cpu, 16 min wall, 0 failures.</li>
  <li><b>Ancestral state reconstruction.</b> ML tree converted to
   ultrametric (extend-tip), VFDB count matrix from ABRicate fed to
   <code>CAFE5 v5.1</code> (<code>quay.io/biocontainers/cafe:5.1.0</code>);
   single-rate birth-death model, 21 iterations, 3.4 min wall.  Per-family
   p-values from CAFE's likelihood-ratio test; per-branch increase/decrease
   from <code>Base_change.tab</code>.</li>
  <li><b>Functional categories.</b> 34,629 pangenome representatives
   (one Prokka-translated protein per Roary cluster) searched against
   COG-2024 reps with DIAMOND blastp (very-sensitive, e-value ≤ 1e-5);
   best-hit COG mapped to functional-category letter via
   cog-24.def.tab.</li>
  <li><b>Genus-wide pangenome.</b> All 262 assemblies re-annotated with
   Prokka (6 parallel × 2 cpu, ~4.6 hours) and clustered with Roary
   <code>-i 90</code> (~2.2 hours, 8 cpu / 28 GB RAM).
   {total_full:,} gene clusters total; {buckets_full.get('Core genes', '?')}
   core genes confirm the 13-genome estimate.</li>
</ol>

<p class="muted">Generated by bioflow comparative_genomics workflow on
 {datetime.now().strftime('%Y-%m-%d %H:%M')}. All Docker images pulled from
 staphb/* BioContainers.</p>
</body></html>"""

(ROOT / "summary.html").write_text(html, encoding="utf-8")
print(f"Report -> {ROOT/'summary.html'}")
