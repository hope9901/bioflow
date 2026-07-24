"""Which recipes CI actually exercises — kept honest, not aspirational.

The docs used to say the smoke matrix runs "each recipe's first stage". It runs
five. Eight of the ten recipes listed as "smoke-tested" had no automated check
at all, so a change to them was caught by nothing.

This pins the real inventory. It fails when coverage *shrinks* (a recipe silently
drops out), and when a recipe gains coverage it fails too — telling you to move
it out of UNCOVERED and update docs/reference/e2e-coverage.md, so the docs can't
drift back into overstating things.
"""
from __future__ import annotations

import re
from pathlib import Path

from bioflow.recipes import names

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = REPO_ROOT / "tests" / "integration"

#: Recipes with a first-stage smoke case (real container).
SMOKE = {
    "prokaryote_assembly", "rnaseq_deg", "amr_vf_catalogue",
    "chip_seq", "germline_variants",
}

#: Recipes whose entire chain runs on a committed fixture.
FULL_E2E = {
    "prokaryote_assembly", "amr_vf_catalogue", "ani_matrix", "pangenome",
    "gwas", "cafe_evolution", "phylogeny", "rnaseq_deg", "methylation_wgbs",
}

#: Recipes guarded at the stage level (their tail needs more data than a
#: committed fixture can honestly provide).
STAGE_GUARDED = {"scrna_seq", "proteomics_dda"}

#: Recipes with **no** automated coverage. Not an allowlist to hide behind —
#: a documented gap. Shrinking it is the goal.
UNCOVERED = {
    "atac_seq", "cog_enrichment", "download_taxon", "eukaryote_assembly",
    "joint_genotyping", "metagenome_assembly", "metagenomics_profile",
}


def test_inventory_accounts_for_every_recipe():
    covered = SMOKE | FULL_E2E | STAGE_GUARDED
    registered = set(names())
    unaccounted = registered - covered - UNCOVERED
    assert not unaccounted, (
        "new recipe(s) missing from the coverage inventory — add them to a "
        f"tier or to UNCOVERED: {sorted(unaccounted)}"
    )
    stale = (covered | UNCOVERED) - registered
    assert not stale, f"inventory lists recipes that no longer exist: {sorted(stale)}"


def test_uncovered_and_covered_do_not_overlap():
    both = UNCOVERED & (SMOKE | FULL_E2E | STAGE_GUARDED)
    assert not both, (
        f"these are listed as uncovered but have a test: {sorted(both)} — "
        "move them out of UNCOVERED and update docs/reference/e2e-coverage.md"
    )


def test_smoke_matrix_matches_the_declared_set():
    """The matrix is hand-built; keep the inventory in step with it."""
    src = (INTEGRATION / "test_recipe_smoke_matrix.py").read_text(encoding="utf-8")
    actual = set(re.findall(r'recipe="([a-z_]+)"', src))
    assert actual == SMOKE, (
        f"smoke matrix now covers {sorted(actual)}; update SMOKE (and the docs) "
        f"— declared {sorted(SMOKE)}"
    )


def test_full_e2e_matches_the_test_file():
    src = (INTEGRATION / "test_full_pipeline_e2e.py").read_text(encoding="utf-8")
    called = set(re.findall(r'get\("([a-z_]+)"\)', src))
    missing = FULL_E2E - called
    assert not missing, f"declared as full-e2e but not run there: {sorted(missing)}"


def test_the_docs_admit_the_gap():
    """The coverage doc must name the uncovered recipes, not imply they're tested."""
    doc = (REPO_ROOT / "docs" / "reference" / "e2e-coverage.md").read_text(
        encoding="utf-8"
    )
    missing = [r for r in UNCOVERED if r not in doc]
    assert not missing, (
        f"docs/reference/e2e-coverage.md doesn't mention {sorted(missing)} "
        "as uncovered"
    )
