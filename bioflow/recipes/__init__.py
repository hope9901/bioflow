"""bioflow recipes — curated end-to-end pipelines.

A *recipe* is a named :class:`bioflow.Pipeline` that ships with bioflow
itself.  Recipes are the Tier-B (researcher) entry point: instead of
writing Python, end-users invoke ``bioflow recipe run <name> [args]``
on the CLI.

Recipes auto-register here when imported.  The CLI walks
``RECIPES`` to list / show / run.

Adding a recipe
---------------
1. Create a module under ``bioflow/recipes/<area>/<name>.py``.
2. Define stages with ``@stage`` and compose them with ``@pipeline``.
3. Register: ``register("name", my_pipeline)``.
4. Import the module from this file's bottom so it auto-registers.
"""
from __future__ import annotations

from typing import Dict

from bioflow.sdk import Pipeline

RECIPES: Dict[str, Pipeline] = {}


def register(name: str, pipe: Pipeline) -> Pipeline:
    """Register a Pipeline under *name* (case-insensitive)."""
    if not isinstance(pipe, Pipeline):
        raise TypeError(f"register() expects a Pipeline, got {type(pipe).__name__}")
    key = name.lower()
    if key in RECIPES and RECIPES[key] is not pipe:
        raise ValueError(f"Recipe {name!r} is already registered")
    RECIPES[key] = pipe
    return pipe


def get(name: str) -> Pipeline:
    """Look up a registered recipe (case-insensitive).  Raises KeyError."""
    key = name.lower()
    if key not in RECIPES:
        avail = ", ".join(sorted(RECIPES))
        raise KeyError(
            f"Unknown recipe {name!r}.  Available: {avail or '<none>'}"
        )
    return RECIPES[key]


def names() -> list:
    return sorted(RECIPES.keys())


# ---------------------------------------------------------------------------
# Auto-import bundled recipes.  Each module calls register() on import.
# ---------------------------------------------------------------------------

# noqa: E402,F401 — these imports trigger registration as a side effect

# Comparative genomics (8 recipes)
from bioflow.recipes.comparative_genomics import pangenome as _pangenome   # noqa
from bioflow.recipes.comparative_genomics import phylogeny as _phylogeny   # noqa
from bioflow.recipes.comparative_genomics import download_taxon as _dl     # noqa
from bioflow.recipes.comparative_genomics import ani_matrix as _ani        # noqa
from bioflow.recipes.comparative_genomics import gwas as _gwas             # noqa
from bioflow.recipes.comparative_genomics import amr_vf_catalogue as _amr  # noqa
from bioflow.recipes.comparative_genomics import cafe_evolution as _cafe   # noqa
from bioflow.recipes.comparative_genomics import cog_enrichment as _cog    # noqa

# Per-pipeline recipes (one per pipeline area)
from bioflow.recipes.genome_assembly import prokaryote_assembly as _asm    # noqa
from bioflow.recipes.genome_assembly import eukaryote_assembly as _euk_asm  # noqa
from bioflow.recipes.rnaseq_deg import rnaseq_deg as _rnaseq               # noqa
from bioflow.recipes.metagenomics import metagenomics_profile as _meta     # noqa
from bioflow.recipes.metagenomics import metagenome_assembly as _meta_asm  # noqa
from bioflow.recipes.single_cell import scrna_seq as _scrna                # noqa
from bioflow.recipes.epigenomics import chip_seq as _chip                  # noqa
from bioflow.recipes.epigenomics import atac_seq as _atac                  # noqa
from bioflow.recipes.methylation import bismark_wgbs as _methyl            # noqa
from bioflow.recipes.proteomics import proteomics_dda as _prot             # noqa
from bioflow.recipes.variant_calling import germline_variants as _gvar     # noqa
