"""Prokaryote de novo assembly + annotation recipe.

End-to-end short-read prokaryote workflow:
    fastp (QC)  →  SPAdes (de novo assembly)  →  QUAST (assembly QC)
                →  Prokka (structural annotation)

Researcher (Tier B) usage::

    bioflow recipe run prokaryote_assembly \\
        --r1 reads_R1.fastq.gz --r2 reads_R2.fastq.gz \\
        --sample-id ecoli_42 --out ./out

Programmatic (Tier A) usage::

    from bioflow.recipes import get
    pipe = get("prokaryote_assembly")
    pipe(r1=Path("R1.fq.gz"), r2=Path("R2.fq.gz"),
         sample_id="my_sample", out_dir=Path("./out"))
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="quay.io/biocontainers/fastp:1.3.6--h43da1c4_0",
       cpu=4, ram_gb=4)
def qc_trim(r1: Path, r2: Path, *, out_dir, min_qual: int = 15):
    """fastp: adapter trim + quality filter for paired-end short reads.

    ``min_qual`` is fastp's per-base quality threshold (its default, 15) —
    override per run with ``--set qc_trim.min_qual=30``.
    """
    return (
        f"fastp -i {r1} -I {r2} "
        f"-o {out_dir}/clean_R1.fastq.gz -O {out_dir}/clean_R2.fastq.gz "
        f"--qualified_quality_phred {min_qual} "
        f"--json {out_dir}/fastp.json --html {out_dir}/fastp.html "
        f"--thread 4"
    )


@stage(image="staphb/spades:4.0.0", cpu=8, ram_gb=16, depends_on=qc_trim,
       retry=2, retry_with={"ram_gb": "2x"})
def assemble(clean, *, out_dir, kmer: str = "auto"):
    """SPAdes de novo assembly from QC-cleaned reads.

    ``kmer`` is SPAdes' ``-k`` (default ``auto``) — override per run with
    ``--set assemble.kmer=21,33,55,77``.
    """
    return (
        f"spades.py "
        f"-1 {clean.out_dir}/clean_R1.fastq.gz "
        f"-2 {clean.out_dir}/clean_R2.fastq.gz "
        f"-k {kmer} "
        f"-o {out_dir} -t 8 -m 16 --only-assembler"
    )


@stage(image="staphb/quast:5.2.0", cpu=2, ram_gb=4, depends_on=assemble)
def assembly_qc(asm, *, out_dir):
    """QUAST: assembly contiguity & completeness metrics.

    Prefers ``scaffolds.fasta``; for very fragmented assemblies SPAdes
    can omit it, so we fall back to the always-present
    ``contigs.fasta``.
    """
    return (
        f"bash -c '"
        f"ASM={asm.out_dir}/scaffolds.fasta; "
        f"[ -f \"$ASM\" ] || ASM={asm.out_dir}/contigs.fasta; "
        f"quast.py -o {out_dir} -t 2 \"$ASM\"'"
    )


@stage(image="staphb/prokka:1.14.6", cpu=4, ram_gb=8, depends_on=assemble)
def annotate(asm, *, out_dir, sample_id: str = "sample"):
    """Prokka: structural annotation (CDS, rRNA, tRNA) on the assembly.

    Same scaffolds → contigs fall-back as ``assembly_qc``.
    """
    return (
        f"bash -c '"
        f"ASM={asm.out_dir}/scaffolds.fasta; "
        f"[ -f \"$ASM\" ] || ASM={asm.out_dir}/contigs.fasta; "
        f"prokka --outdir {out_dir}/prokka --prefix {sample_id} "
        f"--kingdom Bacteria --cpus 4 --force --fast \"$ASM\"'"
    )


@stage(image="staphb/bandage:0.8.1", cpu=2, ram_gb=4, depends_on=assemble)
def graph_image(asm, *, out_dir):
    """Bandage: render the SPAdes assembly graph to a PNG.

    Headless render needs Qt's offscreen platform (no X server in the
    container).  Prefers ``assembly_graph_with_scaffolds.gfa`` and falls back
    to the plain ``assembly_graph.gfa``.
    """
    return (
        f"bash -c 'export QT_QPA_PLATFORM=offscreen; "
        f"GFA={asm.out_dir}/assembly_graph_with_scaffolds.gfa; "
        f"[ -f \"$GFA\" ] || GFA={asm.out_dir}/assembly_graph.gfa; "
        f"Bandage image \"$GFA\" {out_dir}/assembly_graph.png'"
    )


# Standalone filter, kept as a raw string so every backslash (regex escapes,
# ``\n``) reaches the container's Python verbatim through the heredoc.
#
# Why not ``Bio.SeqIO``?  Prokka writes GenBank ``LOCUS`` lines from SPAdes'
# long contig names (``NODE_1_length_283413_cov_6.882027``); when the name
# overflows the fixed-width columns the length field collides with the
# coverage (``…cov_6.882027283413 bp``) and Biopython's strict parser aborts
# the whole file.  We instead split records on ``//`` and read the true length
# from the always-present ``length_<N>`` token in the name, rewriting each
# LOCUS line to a canonical, Biopython-parseable form (GenoVi itself parses
# with Biopython, so the rewrite is what lets it read the assembly at all).
_GENOME_PLOT_FILTER = r'''import sys, re
src, cut, dst = sys.argv[1], int(sys.argv[2]), sys.argv[3]
data = open(src, encoding="utf-8", errors="replace").read()
records = re.split(r"(?m)^//\s*$", data)
out, kept = [], 0
for rec in records:
    rec = rec.strip("\n")
    if not rec.strip():
        continue
    lines = rec.split("\n")
    loc_idx = next((j for j, l in enumerate(lines) if l.startswith("LOCUS")), None)
    if loc_idx is None:
        continue
    m = re.search(r"length_(\d+)", lines[loc_idx])
    if not m:
        continue
    L = int(m.group(1))
    if L < cut:
        continue
    kept += 1
    lines[loc_idx] = "LOCUS       C%-16d%11d bp    DNA     linear   UNK 01-JAN-1980" % (kept, L)
    out.append("\n".join(lines).rstrip("\n") + "\n//")
with open(dst, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + "\n")
sys.stderr.write("genome_plot: kept %d contigs >= %d bp\n" % (kept, cut))
'''


# Post-process: overlay a size-rank number on every contig whose arc is wide
# enough to read (>= 1.2% of the circle), just outside the ideogram ring.
# GenoVi orders contigs largest-first, so this labels the big ones (1, 2, 3 …)
# and leaves the tiny fragments uncluttered.  Circos geometry: 0 at 12 o'clock,
# clockwise, with a 0.001r gap between contigs.  Best effort — any failure
# leaves GenoVi's own PNG untouched.
_GENOME_PLOT_NUMBER = r'''import re, sys, math
from PIL import Image, ImageDraw, ImageFont
gbk, png, out = sys.argv[1], sys.argv[2], sys.argv[3]
RFAC, MINFRAC, GAP = 1.05, 0.012, 0.001   # RFAC>1: sit in the outer white halo
def _font(px):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, px)
        except Exception:
            pass
    return ImageFont.load_default()
try:
    lengths = []
    for line in open(gbk, encoding="utf-8", errors="replace"):
        if line.startswith("LOCUS"):
            m = re.search(r"(\d+)\s+bp", line)
            if m:
                lengths.append(int(m.group(1)))
    n = len(lengths); total = sum(lengths); span = total + n * GAP * total
    img = Image.open(png).convert("RGB"); W, H = img.size
    top = img.crop((0, 0, W, int(H * 0.63))); px = top.load()
    minx, miny, maxx, maxy = W, H, 0, 0
    for y in range(0, top.height, 3):
        for x in range(0, W, 3):
            r, g, b = px[x, y]
            if r < 245 or g < 245 or b < 245:
                minx = min(minx, x); maxx = max(maxx, x); miny = min(miny, y); maxy = max(maxy, y)
    cx = (minx + maxx) / 2; cy = (miny + maxy) / 2; R = max(maxx - minx, maxy - miny) / 2
    d = ImageDraw.Draw(img); fnum = _font(int(R * 0.037)); cum = 0; drawn = 0
    for i, L in enumerate(lengths):
        if L / span >= MINFRAC:
            ang = math.radians(-90 + 360 * (cum + L / 2 + i * GAP * total) / span)
            x = cx + RFAC * R * math.cos(ang); y = cy + RFAC * R * math.sin(ang)
            lbl = str(i + 1); bb = d.textbbox((0, 0), lbl, font=fnum)
            tw = bb[2] - bb[0]; th = bb[3] - bb[1]; pad = int(R * 0.012)
            d.ellipse([x - tw / 2 - pad, y - th / 2 - pad, x + tw / 2 + pad, y + th / 2 + pad], fill=(255, 255, 255))
            d.text((x - tw / 2, y - th / 2 - bb[1]), lbl, font=fnum, fill=(20, 20, 20))
            drawn += 1
        cum += L
    img.save(out, "PNG")
    sys.stderr.write("genome_plot: numbered %d/%d contigs\n" % (drawn, n))
except Exception as e:
    sys.stderr.write("genome_plot: numbering skipped (%s)\n" % e)
    try:
        Image.open(png).save(out, "PNG")
    except Exception:
        pass
'''


@stage(image="staphb/genovi:0.4.3", cpu=4, ram_gb=8, depends_on=annotate)
def genome_plot(ann, *, out_dir, sample_id: str = "sample", min_contig: int = 5000):
    """GenoVi: a Circos-style circular genome map from the Prokka annotation.

    Draws CDS coloured by COG functional category (forward/reverse strands),
    GC content, and GC skew — a publication-style figure that is far more
    legible than the raw assembly graph.

    Circos chokes on the hundreds of sub-kb fragments a draft SPAdes assembly
    leaves behind, so we first drop contigs shorter than ``min_contig``
    (default 5 kb — keeps ~all of a typical bacterial genome; override per run
    with ``--set genome_plot.min_contig=20000`` for a cleaner figure on very
    fragmented assemblies).

    Best effort: the plot is a convenience, so a genome that GenoVi cannot
    render never fails the pipeline (the run's QUAST / Prokka / fastp outputs
    are unaffected).
    """
    gbk = f"{ann.out_dir}/prokka/{sample_id}.gbk"
    return (
        f"cd {out_dir}\n"
        f'python - "{gbk}" "{min_contig}" filtered.gbk <<\'PY\'\n'
        f"{_GENOME_PLOT_FILTER}"
        "PY\n"
        # White background, a colour-blind-safe scheme (Okabe-Ito "autumn"),
        # and -te/-cs give per-track labels + a full feature/COG colour legend
        # so the figure is self-explanatory.
        f'genovi -i filtered.gbk -s draft -o genome '
        f'-bc white -cs autumn -te -t "{sample_id}" || true\n'
        # Overlay contig size-rank numbers on the readable arcs.
        f"python - filtered.gbk genome/genome.png {out_dir}/genome_plot.png <<'PYNUM'\n"
        f"{_GENOME_PLOT_NUMBER}"
        "PYNUM\n"
        # Fallback if the overlay could not run at all.
        f"[ -f {out_dir}/genome_plot.png ] || "
        f"cp genome/genome.png {out_dir}/genome_plot.png 2>/dev/null || true\n"
        "true\n"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[qc_trim, assemble, assembly_qc, graph_image, annotate, genome_plot],
    description="Prokaryote short-read de novo assembly + Prokka annotation",
)
def prokaryote_assembly(
    r1: Path,
    r2: Path,
    *,
    out_dir: Path,
    sample_id: str = "sample",
):
    """fastp → SPAdes → QUAST + Bandage graph + Prokka + GenoVi genome map."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    clean = qc_trim(Path(r1), Path(r2))
    asm = assemble(clean)
    assembly_qc(asm)                # QUAST report lands in its own out_dir
    graph_image(asm)                # Bandage assembly-graph PNG
    ann = annotate(asm, sample_id=sample_id)
    genome_plot(ann, sample_id=sample_id)   # GenoVi circular genome map
    return ann


register("prokaryote_assembly", prokaryote_assembly)
