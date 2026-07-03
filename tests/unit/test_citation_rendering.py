"""Unit tests for the citation-count tooling: gen_docs rendering + the fetch
script's author-name normalisation.  Both live under ``scripts/`` (not the
importable package), so we load them by path."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gd = _load("gen_docs")
fetch = _load("fetch_tool_citations")

_CITES = {
    "deseq2": {"total": 72131, "recent": 52515, "verified": True, "category": "deg"},
    "flye":   {"total": 4700, "recent": 3200, "verified": True, "category": "assembly"},
    "bracken": {"total": None, "recent": None, "verified": False, "category": "metagenomics"},
}
_WINDOW = {"start": 2021, "end": 2025, "years": 5}


# ── gen_docs formatting ──────────────────────────────────────────────────────

def test_fmt_cites_thousands_and_na():
    assert gd._fmt_cites(52515) == "52,515"
    assert gd._fmt_cites(None) == "n/a"
    assert gd._fmt_cites("x") == "n/a"


def test_window_label():
    assert gd._window_label(_WINDOW) == "2021–2025"
    assert gd._window_label(None) == "recent"


def test_leaderboard_ranks_by_recent_and_excludes_unverified():
    md = gd._leaderboard(_CITES, _WINDOW, top=10, level="##")
    assert "Most-used tools" in md and "Cites 2021–2025" in md
    assert md.index("deseq2") < md.index("flye")   # ranked by recent, desc
    assert "bracken" not in md                     # recent is None → excluded
    assert "52,515" in md


def test_landing_html_table_is_well_formed():
    html = gd._landing_leaderboard_html(_CITES, _WINDOW, top=10)
    assert html.startswith("<div") and "<table" in html
    assert html.count("<tr>") == 3                 # 1 header + 2 verified rows
    assert "deseq2" in html and "bracken" not in html
    # each cell carries exactly one style attribute (regression: duplicate attrs)
    assert '" style="' not in html


def test_leaderboard_empty_when_no_recent():
    assert gd._leaderboard({"x": {"recent": None}}, _WINDOW, top=5, level="##") == ""
    assert gd._landing_leaderboard_html({"x": {"recent": None}}, _WINDOW) == ""


# ── fetch author normalisation ───────────────────────────────────────────────

def test_norm_strips_accents_and_case():
    assert fetch._norm("Röst") == "rost"
    assert fetch._norm("Ramírez") == "ramirez"
    assert fetch._norm("Blanco-Míguez") == "blanco-miguez"
    assert fetch._norm("") == ""
