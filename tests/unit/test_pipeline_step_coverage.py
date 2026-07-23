"""`bioflow custom` must actually offer the tools the registry claims to have.

A tool reaches the interactive planner only if its ``stage:`` value equals a step
id defined in ``bioflow/pipelines/*.py``.  Nothing used to check that, so the two
drifted: DeepVariant declared ``variant_calling.call`` while the pipeline defines
``variant_calling.step2``, which made a registered, digest-pinned caller
unselectable — and the QC step of two pipelines offered no tool at all.

These lock both directions of that contract.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import yaml

import bioflow.pipelines as pipelines_pkg
from bioflow.core.compatibility import filter_applicable
from bioflow.core.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "registry"

#: Steps with no registered tool yet.  Each entry is a real gap in the catalogue,
#: not a drift bug — listing it here keeps the guard honest instead of silent.
STEPS_WITHOUT_TOOLS = {
    "proteomics.step5",   # statistics + reporting: no such tool registered yet
}

#: Stage vocabularies used by recipe-only / utility tools that deliberately have
#: no ``bioflow custom`` pipeline behind them (comparative genomics, phylogeny,
#: standalone utilities, cohort-only steps).  Tools here are reachable through
#: their recipe, just not through the interactive planner.
RECIPE_ONLY_STAGES = {
    "comparative_genomics.step2", "comparative_genomics.step3",
    "comparative_genomics.step4", "comparative_genomics.step5",
    "comparative_genomics.step6", "comparative_genomics.step7",
    "comparative_genomics.step8",
    "genome_assembly.step3b", "genome_assembly.step3c", "genome_assembly.trna",
    "metagenomics.sketch",
    "phylogeny.align", "phylogeny.tree", "phylogeny.trim",
    "qc.convert", "rnaseq.count",
    "utility.bam_processing", "utility.genomic_intervals",
    "utility.sequence_ops",
    "variant_calling.joint",   # GLnexus: cohort-only, no single-sample step
}


def _pipeline_steps() -> "dict[str, str]":
    steps: "dict[str, str]" = {}
    for mod_info in pkgutil.iter_modules(pipelines_pkg.__path__):
        mod = importlib.import_module(f"bioflow.pipelines.{mod_info.name}")
        for stage in getattr(mod, "STAGES", []):
            steps[stage["id"]] = stage.get("name", "")
    return steps


def _declared_stages() -> "dict[str, list[str]]":
    declared: "dict[str, list[str]]" = {}
    for path in (REGISTRY / "tools").rglob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for stage in data.get("stage") or []:
            declared.setdefault(stage, []).append(data["id"])
    return declared


def test_every_pipeline_step_offers_at_least_one_tool():
    """An empty step means `bioflow custom` shows the user nothing to pick."""
    steps = _pipeline_steps()
    tools = load_registry(REGISTRY)
    empty = [
        sid for sid in steps
        if sid not in STEPS_WITHOUT_TOOLS
        and not filter_applicable(tools, stage=sid)
    ]
    assert not empty, (
        "these pipeline steps offer no tool — either a tool's `stage:` is "
        f"missing the id, or add it to STEPS_WITHOUT_TOOLS: {sorted(empty)}"
    )


def test_registry_stage_ids_match_a_real_pipeline_step():
    """A `stage:` the planner never asks for silently hides the tool."""
    steps = _pipeline_steps()
    declared = _declared_stages()
    unknown = {
        stage: tools for stage, tools in declared.items()
        if stage not in steps and stage not in RECIPE_ONLY_STAGES
    }
    assert not unknown, (
        "these tools declare a stage no pipeline defines, so `bioflow custom` "
        "can never offer them — fix the id or list it in RECIPE_ONLY_STAGES: "
        f"{ {k: sorted(v) for k, v in sorted(unknown.items())} }"
    )


def test_swap_alternatives_are_selectable_in_custom():
    """Every tool a recipe exposes via `--set` should also be reachable through
    the interactive planner — they are the same catalogue."""
    steps = _pipeline_steps()
    tools = load_registry(REGISTRY)
    offered = {
        t.id for sid in steps for t in filter_applicable(tools, stage=sid)
    }
    # Alternatives shipped as `--set` swaps that belong to a custom pipeline.
    expected = {
        "deepvariant",   # --set caller=deepvariant
        "kb_python",     # --set counter=kb
        "msgf_plus",     # --set search=msgf
        "maxbin2",       # --set binner=maxbin2
        "bakta",         # --set annotator=bakta
        "hifiasm",       # --set assembler=hifiasm
        "kallisto",      # --set quantifier=kallisto
    }
    missing = sorted(t for t in expected if t not in offered)
    assert not missing, (
        f"swap alternatives not selectable in `bioflow custom`: {missing}"
    )
