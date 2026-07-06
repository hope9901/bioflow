"""Unit tests for `bioflow cite` — tool-citation resolution + formatting.

Offline: uses the committed registry YAMLs + registry/tool_citations.json.
"""
from __future__ import annotations

from bioflow.core import citations


def test_citations_for_recipe_maps_stages_to_tools():
    entries = citations.citations_for_recipe("prokaryote_assembly")
    ids = {e["id"] for e in entries}
    # the recipe's real tools resolve, deduped
    assert {"fastp", "spades", "quast", "prokka"} <= ids
    assert len(ids) == len(entries)                      # no duplicates
    spades = next(e for e in entries if e["id"] == "spades")
    assert spades["version"] and spades["doi"]           # verified → has a DOI


def test_citations_for_tools_reports_unknown():
    entries, unknown = citations.citations_for_tools(["prokka", "definitely_not_a_tool"])
    assert [e["id"] for e in entries] == ["prokka"]
    assert unknown == ["definitely_not_a_tool"]


def test_unverified_tool_has_no_doi():
    # bracken's paper has no MEDLINE record → unverified → no DOI on file
    entries, _ = citations.citations_for_tools(["bracken"])
    assert entries and entries[0]["doi"] is None


def test_format_text_strips_pmid_and_adds_doi_link():
    entries, _ = citations.citations_for_tools(["prokka"])
    txt = citations.format_text(entries)
    assert "Prokka" in txt
    assert "https://doi.org/" in txt
    assert "PMID" not in txt                              # PMID stripped from the ref


def test_format_bibtex_is_well_formed():
    entries, _ = citations.citations_for_tools(["prokka"])
    bib = citations.format_bibtex(entries)
    assert bib.startswith("@software{prokka,")
    assert "doi = {" in bib and bib.rstrip().endswith("}")
