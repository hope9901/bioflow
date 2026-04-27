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
The pangenome is wide-open: only {buckets.get('Core genes',0)} genes are core
across all 13 species, but the pan-genome reaches {total:,} clusters and is still rising.
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

<h2>6 · Methods</h2>
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
</ol>

<p class="muted">Generated by bioflow comparative_genomics workflow on
 {datetime.now().strftime('%Y-%m-%d %H:%M')}. All Docker images pulled from
 staphb/* BioContainers.</p>
</body></html>"""

(ROOT / "summary.html").write_text(html, encoding="utf-8")
print(f"Report -> {ROOT/'summary.html'}")
