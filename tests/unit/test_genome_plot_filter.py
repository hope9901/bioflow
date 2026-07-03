"""Unit tests for the prokaryote_assembly ``genome_plot`` in-container helpers.

The stage runs two self-contained Python snippets inside the GenoVi container
(so they can't import bioflow).  The tricky one is ``_GENOME_PLOT_FILTER``: it
rewrites Prokka's malformed GenBank ``LOCUS`` lines — where a long SPAdes contig
name collides the length with the coverage (``…cov_6.882027350000 bp``) and
aborts Biopython's strict parser — into a canonical form, while dropping contigs
below a size cutoff.  We exec the snippet here (it uses only ``re`` + file IO)
and check the round-trip: filtered, renumbered, and Biopython-parseable.
"""
from __future__ import annotations

import sys

from bioflow.recipes.genome_assembly.prokaryote_assembly import _GENOME_PLOT_FILTER

# Two contigs with the real "length jammed into coverage" malformation; the
# 20 bp ORIGIN matches the declared length so Biopython is happy after rewrite.
_MALFORMED_GBK = (
    "LOCUS       NODE_1_length_20_cov_6.88202720 bp   DNA linear\n"
    "FEATURES             Location/Qualifiers\n"
    "     source          1..20\n"
    "ORIGIN\n"
    "        1 acgtacgtac gtacgtacgt\n"
    "//\n"
    "LOCUS       NODE_2_length_5_cov_3.05005 bp   DNA linear\n"
    "ORIGIN\n"
    "        1 acgta\n"
    "//\n"
)


def _run_filter(src, cutoff, dst):
    argv = ["-", str(src), str(cutoff), str(dst)]
    old = sys.argv
    sys.argv = argv
    try:
        exec(compile(_GENOME_PLOT_FILTER, "<genome_plot_filter>", "exec"), {})
    finally:
        sys.argv = old


def test_filter_drops_small_and_normalises_locus(tmp_path):
    src = tmp_path / "in.gbk"
    src.write_text(_MALFORMED_GBK, encoding="utf-8")
    out = tmp_path / "filtered.gbk"

    _run_filter(src, 10, out)          # cutoff 10 bp → keep NODE_1 (20), drop NODE_2 (5)
    text = out.read_text(encoding="utf-8")

    assert text.count("LOCUS") == 1          # only the >= cutoff contig survives
    assert "NODE_2" not in text
    # LOCUS rewritten to a clean, fixed-width, dated line Biopython can read
    assert "C1" in text and "20 bp" in text and "01-JAN-1980" in text
    assert "cov_6.88202720" not in text      # the malformed original line is gone


def test_filter_output_parses_with_biopython(tmp_path):
    import pytest
    SeqIO = pytest.importorskip("Bio.SeqIO")   # Bio lives in the container, not CI

    src = tmp_path / "in.gbk"
    src.write_text(_MALFORMED_GBK, encoding="utf-8")
    out = tmp_path / "filtered.gbk"
    _run_filter(src, 10, out)

    recs = list(SeqIO.parse(str(out), "genbank"))   # must not raise
    assert len(recs) == 1
    assert len(recs[0].seq) == 20


def test_filter_keeps_all_when_cutoff_low(tmp_path):
    src = tmp_path / "in.gbk"
    src.write_text(_MALFORMED_GBK, encoding="utf-8")
    out = tmp_path / "filtered.gbk"
    _run_filter(src, 1, out)
    assert out.read_text(encoding="utf-8").count("LOCUS") == 2
