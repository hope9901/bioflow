"""Unit tests for the results harvester + overview (visualization Layers 1 & 2).

Synthetic QUAST/Prokka fixture files — no Docker, no real assembly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bioflow.core.results import (
    _parse_prokka,
    _parse_quast,
    build_overview,
)


def _mk_sample(root: Path, sid: str, *, contigs, total, n50, gc, cds, rrna, trna):
    """Write a sample's QUAST + Prokka + fastp outputs (data files AND the
    tools' own report pages) under a hidden .cache, mimicking a finished run."""
    q = root / sid / ".cache" / f"assembly_qc__{sid}h"
    q.mkdir(parents=True)
    (q / "report.tsv").write_text(
        "Assembly\tscaffolds\n"
        f"# contigs (>= 0 bp)\t{contigs + 50}\n"      # must be ignored
        f"# contigs\t{contigs}\n"
        f"Total length (>= 0 bp)\t{total + 9000}\n"   # must be ignored
        f"Total length\t{total}\n"
        f"N50\t{n50}\n"
        f"GC (%)\t{gc}\n"
        f"Largest contig\t{n50 * 2}\n",
        encoding="utf-8",
    )
    (q / "report.html").write_text("<html>quast</html>", encoding="utf-8")
    (q / "icarus.html").write_text("<html>icarus</html>", encoding="utf-8")
    p = root / sid / ".cache" / f"annotate__{sid}h" / "prokka"
    p.mkdir(parents=True)
    (p / f"{sid}.txt").write_text(
        f"organism: Genus species {sid}\ncontigs: {contigs}\nbases: {total}\n"
        f"CDS: {cds}\nrRNA: {rrna}\ntRNA: {trna}\n",
        encoding="utf-8",
    )
    qc = root / sid / ".cache" / f"qc_trim__{sid}h"
    qc.mkdir(parents=True)
    (qc / "fastp.html").write_text("<html>fastp</html>", encoding="utf-8")
    g = root / sid / ".cache" / f"graph_image__{sid}h"
    g.mkdir(parents=True)
    (g / "assembly_graph.png").write_bytes(b"\x89PNG\r\n\x1a\n")   # Bandage output
    gp = root / sid / ".cache" / f"genome_plot__{sid}h"
    gp.mkdir(parents=True)
    (gp / "genome_plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")     # GenoVi output


def test_parse_quast_takes_bare_metrics(tmp_path):
    f = tmp_path / "report.tsv"
    f.write_text(
        "# contigs (>= 0 bp)\t999\n# contigs\t353\nTotal length\t6033993\n"
        "N50\t30700\nGC (%)\t37.46\nLargest contig\t149871\n",
        encoding="utf-8",
    )
    d = _parse_quast(f)
    assert d == {"n_contigs": 353, "total_bp": 6033993, "n50": 30700,
                 "gc_pct": 37.46, "largest_contig": 149871}


def test_parse_prokka(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("organism: x\ncontigs: 252\nbases: 4812425\nCDS: 4594\n"
                 "rRNA: 9\ntRNA: 90\n", encoding="utf-8")
    d = _parse_prokka(f)
    assert d == {"n_contigs": 252, "total_bp": 4812425, "cds": 4594,
                 "rrna": 9, "trna": 90}


def test_build_overview_end_to_end(tmp_path):
    out = tmp_path / "out"
    _mk_sample(out, "S1", contigs=300, total=5_000_000, n50=40000, gc=37.5,
               cds=4800, rrna=9, trna=80)
    _mk_sample(out, "S2", contigs=200, total=4_000_000, n50=90000, gc=41.0,
               cds=4000, rrna=6, trna=70)

    res = build_overview("prokaryote_assembly", out)
    rows = {r["sample_id"]: r for r in res["rows"]}
    assert set(rows) == {"S1", "S2"}
    # QUAST wins for shared metrics; values land tidily
    assert rows["S1"]["total_bp"] == 5_000_000
    assert rows["S1"]["n50"] == 40000 and rows["S1"]["gc_pct"] == 37.5
    assert rows["S1"]["cds"] == 4800 and rows["S1"]["trna"] == 80

    # Layer 1 artifacts
    assert Path(res["csv"]).exists()
    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert manifest["recipe"] == "prokaryote_assembly"
    assert manifest["n_samples"] == 2
    assert manifest["tables"][0]["columns"][0] == "sample_id"
    # manifest indexes each tool's own report page (relative, forward slashes)
    assert set(manifest["reports"]["S1"]) == {
        "Circular genome map (GenoVi)", "QUAST report", "Icarus contig browser",
        "fastp read QC", "Assembly graph (Bandage)"}
    assert manifest["reports"]["S1"]["QUAST report"].endswith("report.html")
    assert "\\" not in manifest["reports"]["S1"]["QUAST report"]

    # Layer 2 artifact — table + links to the tools' own reports (not redrawn);
    # image outputs (GenoVi + Bandage PNGs) are embedded, HTML pages are linked.
    page = Path(res["overview"]).read_text(encoding="utf-8")
    assert "S1" in page and "S2" in page
    assert "QUAST report" in page and "Icarus contig browser" in page
    assert "report.html" in page
    assert "<img" in page and "assembly_graph.png" in page
    assert "Circular genome map (GenoVi)" in page and "genome_plot.png" in page


def test_build_overview_unknown_recipe_raises(tmp_path):
    with pytest.raises(ValueError, match="No results harvester"):
        build_overview("rnaseq_deg", tmp_path)


def test_build_overview_empty_workspace_raises(tmp_path):
    with pytest.raises(ValueError, match="No per-sample outputs"):
        build_overview("prokaryote_assembly", tmp_path)


# ---------------------------------------------------------------------------
# maybe_build_overview — best-effort end-of-run hook (never raises)
# ---------------------------------------------------------------------------

def test_maybe_overview_unknown_recipe_is_none(tmp_path):
    from bioflow.core.results import maybe_build_overview
    assert maybe_build_overview("rnaseq_deg", tmp_path) is None


def test_maybe_overview_swallows_errors(tmp_path):
    from bioflow.core.results import maybe_build_overview
    # known recipe but empty workspace → build raises → hook returns None
    assert maybe_build_overview("prokaryote_assembly", tmp_path) is None


def test_maybe_overview_success(tmp_path):
    from bioflow.core.results import maybe_build_overview
    out = tmp_path / "out"
    _mk_sample(out, "S1", contigs=300, total=5_000_000, n50=40000, gc=37.5,
               cds=4800, rrna=9, trna=80)
    res = maybe_build_overview("prokaryote_assembly", out)
    assert res is not None and Path(res["overview"]).exists()


# ---------------------------------------------------------------------------
# metagenomics_profile harvester (2nd recipe — Bracken + Krona)
# ---------------------------------------------------------------------------

def _mk_meta_sample(root: Path, sid: str) -> None:
    b = root / sid / ".cache" / f"bracken_abundance__{sid}h"
    b.mkdir(parents=True)
    (b / f"{sid}.bracken.tsv").write_text(
        "name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\t"
        "new_est_reads\tfraction_total_reads\n"
        "Escherichia coli\t562\tS\t8000\t1200\t9200\t0.46\n"
        "Bacillus subtilis\t1423\tS\t5000\t800\t5800\t0.29\n",
        encoding="utf-8",
    )
    k = root / sid / ".cache" / f"krona_chart__{sid}h"
    k.mkdir(parents=True)
    (k / "krona.html").write_text("<html>krona</html>", encoding="utf-8")


def test_metagenomics_overview_end_to_end(tmp_path):
    out = tmp_path / "out"
    _mk_meta_sample(out, "M1")
    res = build_overview("metagenomics_profile", out)
    row = {r["sample_id"]: r for r in res["rows"]}["M1"]
    assert row["classified_reads"] == 15000 and row["n_taxa"] == 2
    assert row["top_taxon"] == "Escherichia coli" and row["top_fraction"] == 0.46

    # Layer 1 — a metagenomics-specific tidy table (not assembly_metrics.csv)
    assert Path(res["csv"]).name == "taxonomic_profile.csv"
    manifest = json.loads(Path(res["manifest"]).read_text(encoding="utf-8"))
    assert "Krona taxonomy (interactive)" in manifest["reports"]["M1"]

    # Layer 2 — overview links the interactive Krona report + the right columns
    page = Path(res["overview"]).read_text(encoding="utf-8")
    assert "Krona taxonomy (interactive)" in page and "krona.html" in page
    assert "top_taxon" in page and "taxonomic_profile.csv" in page
