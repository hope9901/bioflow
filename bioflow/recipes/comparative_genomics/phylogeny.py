"""Phylogeny recipe — Roary GFFs → core supermatrix → IQ-TREE ML.

Mirrors the approach we developed manually in session 1
(``analysis/dickeya/build_core_alignment.py`` + ``run_iqtree_full.py``)
but expressed against the SDK so any dependency change auto-invalidates
just the affected stages.

Pipeline structure
------------------
::

    pick_core ──┐
                ├─→ extract_per_gene ──→ mafft × N → concat → iqtree
    (Roary GFFs)│                          (parallel)
                └─ … (depends_on chain)

Researcher (Tier B) usage
-------------------------
    $ bioflow recipe run phylogeny --gff-dir <dir-of-prokka-gffs>

Programmatic (Tier A) usage
---------------------------
    from bioflow.recipes import get
    pipe = get("phylogeny")
    pipe(gff_dir=Path("./pangenome/gffs"), out_dir=Path("./tree"))
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from bioflow import stage, pipeline
from bioflow.io import write_text
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="staphb/mafft:7.526", cpu=1, ram_gb=2)
def mafft_one(gene_fasta: Path, *, out_dir):
    """Align one gene's per-strain CDS file with MAFFT --auto."""
    return (
        f"sh -c 'mafft --auto --quiet --thread 1 "
        f"{gene_fasta} > {out_dir}/{gene_fasta.stem}.aln'"
    )


@stage(
    image="staphb/iqtree2:2.4.0",
    cpu=4, ram_gb=8,
    depends_on=mafft_one,
    retry=1, retry_with={"ram_gb": "2x"},
)
def run_iqtree(supermatrix: Path, *, out_dir,
               model: str = "GTR+G", bootstrap: int = 1000):
    """Build an ML tree from a concatenated supermatrix."""
    return (
        f"iqtree2 -s {supermatrix} -m {model} -bb {bootstrap} -nt 4 "
        f"-redo -pre {out_dir}/iqtree"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[mafft_one, run_iqtree],
    description="Single-copy core gene supermatrix → MAFFT × N → IQ-TREE ML",
)
def phylogeny(
    gff_dir: Path,
    *,
    out_dir: Path,
    n_genes: int = 50,
    iqtree_model: str = "GTR+G",
    bootstrap: int = 1000,
    _gpa_csv: Optional[Path] = None,
    _ffn_dir: Optional[Path] = None,
):
    """Build a maximum-likelihood phylogeny from a directory of Prokka GFFs.

    The function tries to find a co-located Roary
    ``gene_presence_absence.csv`` to identify single-copy core genes.
    If absent, the user can pass ``_gpa_csv`` explicitly.

    Steps:
      1. Pick *n_genes* longest single-copy core genes (≥99% strain
         prevalence, exactly one copy per strain).
      2. For each, gather the per-strain CDS into a FASTA.
      3. MAFFT-align each in parallel (``parallel="auto"``).
      4. Concatenate into a supermatrix.
      5. IQ-TREE 2 with model auto / bootstrap.

    Returns the :class:`StageResult` of the IQ-TREE run.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    gff_dir = Path(gff_dir).resolve()

    # ── 1+2. Prepare per-gene FASTAs (host-side; cheap I/O) ────────────────
    gene_fastas = _build_per_gene_fastas(
        gff_dir=gff_dir,
        gpa_csv=_gpa_csv,
        ffn_dir=_ffn_dir,
        n_genes=n_genes,
        scratch=out_dir / "_per_gene",
    )
    if not gene_fastas:
        raise RuntimeError(
            f"No single-copy core genes found under {gff_dir}.  "
            "Ensure the directory contains Prokka GFF + a Roary "
            "gene_presence_absence.csv (or pass _gpa_csv)."
        )

    # ── 3. Parallel MAFFT ──────────────────────────────────────────────────
    aligned = mafft_one.map(gene_fastas, parallel="auto", progress=True)

    # ── 4. Concatenate per-strain rows → supermatrix.fna ──────────────────
    supermatrix = _concatenate_alignments(
        aligned_dirs=[r.out_dir for r in aligned if r.ok],
        gene_names=[p.stem for p in gene_fastas],
        out_path=out_dir / "core_supermatrix.fna",
    )

    # ── 5. ML tree ─────────────────────────────────────────────────────────
    return run_iqtree(
        supermatrix, model=iqtree_model, bootstrap=bootstrap,
    )


# ---------------------------------------------------------------------------
# Helpers (host-side, deterministic)
# ---------------------------------------------------------------------------

def _build_per_gene_fastas(
    *, gff_dir: Path, gpa_csv: Optional[Path], ffn_dir: Optional[Path],
    n_genes: int, scratch: Path,
) -> list:
    """Return a list of per-gene FASTA Paths (one file per gene cluster)."""
    import pandas as pd

    if gpa_csv is None:
        cands = list(gff_dir.parent.rglob("gene_presence_absence.csv"))
        if not cands:
            return []
        gpa_csv = sorted(cands, key=lambda p: len(str(p)))[0]
    if ffn_dir is None:
        ffn_dir = gff_dir   # Prokka emits .ffn next to .gff by default

    scratch.mkdir(parents=True, exist_ok=True)
    gpa = pd.read_csv(gpa_csv, low_memory=False)
    meta = {
        "Gene", "Non-unique Gene name", "Annotation", "No. isolates",
        "No. sequences", "Avg sequences per isolate", "Genome Fragment",
        "Order within Fragment", "Accessory Fragment",
        "Accessory Order with Fragment", "QC", "Min group size nuc",
        "Max group size nuc", "Avg group size nuc",
    }
    sample_cols = [c for c in gpa.columns if c not in meta]
    n_strains = len(sample_cols)
    sc_core = gpa[
        (gpa["No. isolates"] >= int(n_strains * 0.99))
        & (gpa["No. sequences"] == gpa["No. isolates"])
    ].copy()
    if "Avg group size nuc" in sc_core.columns:
        sc_core = sc_core.sort_values("Avg group size nuc", ascending=False)
    selected = sc_core.head(n_genes)

    # Index every strain's nucleotide CDS by locus tag
    strain_seqs: dict[str, dict[str, str]] = {}
    for s in sample_cols:
        ffn = ffn_dir / f"{s}.ffn"
        if not ffn.exists():
            # Try sibling of the GFF
            ffn = (gff_dir / f"{s}.ffn")
        if not ffn.exists():
            continue
        seqs: dict[str, str] = {}
        cur_id = None
        cur: list = []
        for line in ffn.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(">"):
                if cur_id:
                    seqs[cur_id] = "".join(cur)
                cur_id = line[1:].split()[0]
                cur = []
            else:
                cur.append(line.strip())
        if cur_id:
            seqs[cur_id] = "".join(cur)
        strain_seqs[s] = seqs

    fasta_paths: list = []
    for _, row in selected.iterrows():
        g = row["Gene"]
        out = scratch / f"{g}.fna"
        chunks: list = []
        for s in sample_cols:
            lt = row.get(s, "")
            if not isinstance(lt, str) or not lt.strip():
                continue
            lt = lt.split()[0]
            seq = strain_seqs.get(s, {}).get(lt, "")
            if seq:
                chunks.append(f">{s}\n{seq}")
        if chunks:
            write_text(out, "\n".join(chunks) + "\n")
            fasta_paths.append(out)
    return fasta_paths


def _concatenate_alignments(
    *, aligned_dirs: list, gene_names: list, out_path: Path,
) -> Path:
    """Walk MAFFT output directories, concatenate per-strain rows, write FASTA."""
    strain_seqs: dict[str, list] = {}
    for d, gene in zip(aligned_dirs, gene_names):
        aln = d / f"{gene}.aln"
        if not aln.exists():
            continue
        rec: dict[str, list] = {}
        cur = None
        for line in aln.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(">"):
                cur = line[1:].split()[0]
                rec[cur] = []
            elif cur:
                rec[cur].append(line.strip())
        seq_lens = {len("".join(v)) for v in rec.values()}
        if len(seq_lens) != 1:
            continue   # skip alignments that didn't align cleanly
        L = seq_lens.pop()
        for s in (set(strain_seqs) | set(rec)):
            joined = "".join(rec.get(s, [])) or ("-" * L)
            strain_seqs.setdefault(s, []).append(joined)

    parts: list = []
    for s, seqs in sorted(strain_seqs.items()):
        parts.append(f">{s}\n{''.join(seqs)}")
    write_text(out_path, "\n".join(parts) + "\n")
    return out_path


register("phylogeny", phylogeny)
