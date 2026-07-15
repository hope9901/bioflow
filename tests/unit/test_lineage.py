"""BUSCO/compleasm lineage recommender.

A more specific taxon hint must win over the species default, common organisms
must resolve to the expected odb10 dataset, and catalogued lineages must point
at a real `bioflow db` key.

See bioflow/core/lineage.py.
"""
from __future__ import annotations

import pytest

from bioflow.core import db
from bioflow.core.lineage import recommend_lineage


@pytest.mark.parametrize("taxon,expected", [
    ("fungus", "fungi_odb10"),
    ("baker's yeast", "saccharomycetes_odb10"),
    ("insect", "insecta_odb10"),
    ("Drosophila melanogaster", "diptera_odb10"),
    ("human", "primates_odb10"),
    ("zebrafish", "actinopterygii_odb10"),
    ("Arabidopsis (a plant)", "viridiplantae_odb10"),
    ("E. coli bacterium", "bacteria_odb10"),
])
def test_taxon_hint_resolves(taxon, expected):
    assert recommend_lineage(taxon=taxon)["lineage"] == expected


def test_species_default_when_no_taxon():
    assert recommend_lineage(species="prokaryote")["lineage"] == "bacteria_odb10"
    assert recommend_lineage(species="eukaryote")["lineage"] == "eukaryota_odb10"


def test_taxon_beats_species_default():
    rec = recommend_lineage(species="eukaryote", taxon="mushroom")
    assert rec["lineage"] == "basidiomycota_odb10"
    assert "taxon match" in rec["source"]


def test_catalogued_lineage_points_at_real_db_key():
    rec = recommend_lineage(species="prokaryote")            # bacteria_odb10
    assert rec["db_key"] == "busco_bacteria"
    assert rec["db_key"] in db._DB_CATALOG


def test_uncatalogued_lineage_gives_download_hint():
    rec = recommend_lineage(taxon="fungus")                  # not catalogued
    assert rec["db_key"] is None
    assert "busco --download" in rec["how"]
