"""Smoke tests for the per-pipeline recipes added in v0.1.4.

These verify each new recipe registers under the expected name and
exposes a DAG of the expected stage count.  Full end-to-end execution
requires real Docker + real reference data (genome indices etc.) so it
lives in tests/e2e/, not here.
"""
from __future__ import annotations

import pytest

from bioflow.recipes import get, names


EXPECTED_RECIPES = {
    "prokaryote_assembly":  7,   # fastp → spades → quast → bandage → prokka|bakta → genovi
    "eukaryote_assembly":   5,   # nanoplot → flye|hifiasm → medaka → compleasm
    "rnaseq_deg":           8,   # fastp → salmon|kallisto (index+quant) → deseq2 → enrich → multiqc
    "metagenomics_profile": 5,   # fastp → kraken2 → bracken → krona
    "metagenome_assembly":  6,   # fastp → megahit → minimap2 → metabat2 → checkm2
    "scrna_seq":            4,   # starsolo | kb_ref → kb_count → scanpy
    "chip_seq":             6,   # trim → align → dedup → peaks → annotate
    "atac_seq":             6,   # trim → align → dedup → peaks → footprint
    "methylation_wgbs":     4,   # trim → bismark_prep → bismark → methylkit
    "proteomics_dda":       5,   # msconvert → comet→percolator | msgf→msgf_fdr
    "germline_variants":    7,   # fastp → prep_ref → bwa → gatk → bcftools → snpeff
    "joint_genotyping":    11,   # cohort: prep_ref → qc → align → gvcf(gatk|dv) → combine/genotype|glnexus(+bcftools) → filter → snpeff
}


class TestPerPipelineRegistry:

    def test_all_per_pipeline_recipes_registered(self):
        registered = set(names())
        missing = set(EXPECTED_RECIPES) - registered
        assert not missing, f"Missing recipes: {missing}"

    @pytest.mark.parametrize("recipe_name,n_stages", list(EXPECTED_RECIPES.items()))
    def test_recipe_dag_shape(self, recipe_name, n_stages):
        pipe = get(recipe_name)
        plan = pipe.dry_run()
        assert plan["n_stages"] == n_stages, (
            f"{recipe_name}: expected {n_stages} stages, "
            f"got {plan['n_stages']}"
        )

    @pytest.mark.parametrize("recipe_name", list(EXPECTED_RECIPES))
    def test_recipe_has_description(self, recipe_name):
        pipe = get(recipe_name)
        assert pipe.description, f"{recipe_name}: empty description"


class TestRegistryTotal:
    """8 comparative genomics + 12 per-pipeline = 20 recipes."""

    def test_total_recipe_count(self):
        registered = set(names())
        assert len(registered) >= 20, (
            f"Expected ≥20 recipes, got {len(registered)}: "
            f"{sorted(registered)}"
        )
