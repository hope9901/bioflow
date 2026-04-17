"""Pipeline planner.

Builds an ExecutionPlan from:
  - A preset YAML  +  a user config YAML  (recommend / bioflow recommend mode)
  - A previously saved full ExecutionPlan YAML            (bioflow run mode)
  - Interactive questionary prompts                       (bioflow custom mode — step 8)

Artifact chaining
-----------------
Each pipeline stage produces output files whose paths are derived from the
stage's working directory (<workdir>/<stage_id_with_underscores>/).  The
planner knows the conventional output filenames for each stage/tool and stores
them in STAGE_ARTIFACT_PATHS.  When it builds the StagePlan list it fills in
each stage's `params` dict so that downstream stages receive the correct paths
even before the run starts.

Example (genome_assembly, prokaryote short):

  step1 fastp  → clean_R1.fastq.gz, clean_R2.fastq.gz
  step2 spades ← {r1}/{r2} from step1 → scaffolds.fasta
  step3 quast  ← {assembly_fasta} from step2
  step4 ---    (skipped for prokaryote)
  step5 prokka ← {assembly_fasta} from step2 → {sample_id}.gff, .faa
  step6 eggnog ← {protein_faa} from step5
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from bioflow.core.compatibility import classify
from bioflow.core.hardware import detect
from bioflow.core.logger import get_logger
from bioflow.core.registry import load_registry

log = get_logger()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class StagePlan(BaseModel):
    stage_id: str                          # e.g. "genome_assembly.step2"
    tool_id: str                           # resolved tool id from registry
    params: dict = Field(default_factory=dict)  # per-invocation path overrides


class ExecutionPlan(BaseModel):
    pipeline: str                          # "genome_assembly" | "rnaseq_deg"
    preset: Optional[str] = None
    species: str
    read_type: str
    mode: str
    inputs: dict = Field(default_factory=dict)   # global inputs (raw paths, sample_id…)
    stages: list[StagePlan] = Field(default_factory=list)
    workdir: Path
    registry_dir: Path = Path("registry")


class _PresetStage(BaseModel):
    stage_id: str
    tool_id: Optional[str] = None
    skip: bool = False
    reason: str = ""
    params: dict = Field(default_factory=dict)


class _Preset(BaseModel):
    id: str
    pipeline: str
    description: str = ""
    applies_to: dict = Field(default_factory=dict)
    stages: list[_PresetStage]


class _UserConfig(BaseModel):
    pipeline: str
    species: str
    read_type: str
    mode: str
    inputs: dict = Field(default_factory=dict)
    workdir: Path
    registry_dir: Path = Path("registry")


# ---------------------------------------------------------------------------
# Artifact path conventions
# ---------------------------------------------------------------------------

# Convention: each entry maps (stage_id, tool_id) → {param_key: filename_within_stage_dir}.
# These filenames are the *standard* outputs for that tool.
# "tool_id=None" means the convention applies regardless of which tool runs the stage.
_ARTIFACT_FILENAMES: dict[tuple[str, Optional[str]], dict[str, str]] = {
    # Genome assembly
    ("genome_assembly.step1", None):         {"r1": "clean_R1.fastq.gz",
                                              "r2": "clean_R2.fastq.gz"},
    ("genome_assembly.step2", "spades"):     {"assembly_fasta": "scaffolds.fasta"},
    ("genome_assembly.step2", "hifiasm"):    {"assembly_fasta": "asm.bp.p_ctg.fa"},
    ("genome_assembly.step2", "flye"):       {"assembly_fasta": "assembly.fasta"},
    ("genome_assembly.step2", "unicycler"):  {"assembly_fasta": "assembly.fasta"},
    ("genome_assembly.step4", None):         {"masked_assembly_fasta": "genome.masked.fasta"},
    ("genome_assembly.step5", "prokka"):     {"structural_gff": "{sample_id}.gff",
                                              "protein_faa":    "{sample_id}.faa"},
    ("genome_assembly.step5", "bakta"):      {"structural_gff": "{sample_id}.gff",
                                              "protein_faa":    "{sample_id}.faa"},
    ("genome_assembly.step5", "braker3"):    {"structural_gff": "braker.gff3",
                                              "protein_faa":    "braker.aa"},
    # RNA-seq DEG
    ("rnaseq_deg.step1", None):              {"r1": "clean_R1.fastq.gz",
                                              "r2": "clean_R2.fastq.gz"},
    ("rnaseq_deg.step2", "salmon"):          {"count_matrix": "quant.sf"},
    ("rnaseq_deg.step2", "kallisto"):        {"count_matrix": "abundance.tsv"},
    ("rnaseq_deg.step2", "hisat2"):          {"alignment_bam": "aligned.bam",
                                              "count_matrix":  "counts.tsv"},
    ("rnaseq_deg.step2", "star"):            {"alignment_bam": "Aligned.sortedByCoord.out.bam",
                                              "count_matrix":  "ReadsPerGene.out.tab"},
    ("rnaseq_deg.step3", None):              {"deg_table": "deg_results.tsv"},
    ("rnaseq_deg.step4", None):              {"enrichment_report": "enrichment_report.html"},
}


def _stage_dir(workdir: Path, stage_id: str) -> Path:
    return workdir / stage_id.replace(".", "_")


def _resolve_filename(filename: str, user_inputs: dict) -> str:
    """Expand {sample_id} and similar user-provided tokens in filenames."""
    try:
        return filename.format(**user_inputs)
    except KeyError:
        return filename  # leave unresolved; runner will warn


def _artifact_paths(
    stage_id: str,
    tool_id: str,
    stage_dir: Path,
    user_inputs: dict,
) -> dict[str, str]:
    """Return {param_key: absolute_path} for the standard outputs of a stage."""
    result: dict[str, str] = {}
    for key in [(stage_id, tool_id), (stage_id, None)]:
        if key in _ARTIFACT_FILENAMES:
            for param, fname in _ARTIFACT_FILENAMES[key].items():
                result[param] = str(stage_dir / _resolve_filename(fname, user_inputs))
            break
    return result


# ---------------------------------------------------------------------------
# Core planner functions
# ---------------------------------------------------------------------------

def plan_from_preset(preset_name: str, config: Path) -> ExecutionPlan:
    """Build an ExecutionPlan from a preset name + user config file.

    Steps:
      1. Load & validate user config YAML
      2. Load preset YAML from <registry_dir>/presets/<preset_name>.yaml
      3. Detect hardware → classify tools → warn on slow/incompatible
      4. Walk preset stages, skip if skip=true, chain artifacts
      5. Return populated ExecutionPlan
    """
    with config.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    user_cfg = _UserConfig.model_validate(raw)

    preset_path = user_cfg.registry_dir / "presets" / f"{preset_name}.yaml"
    if not preset_path.exists():
        raise FileNotFoundError(
            f"Preset '{preset_name}' not found at {preset_path}"
        )
    with preset_path.open("r", encoding="utf-8") as f:
        preset = _Preset.model_validate(yaml.safe_load(f))

    if preset.pipeline != user_cfg.pipeline:
        raise ValueError(
            f"Preset pipeline '{preset.pipeline}' != config pipeline '{user_cfg.pipeline}'"
        )

    tools = load_registry(user_cfg.registry_dir)
    tools_by_id = {t.id: t for t in tools}
    hw = detect()
    classified = classify(tools, hw)
    slow_ids = {t.id for t in classified["runnable_slow"]}
    bad_ids  = {t.id for t in classified["incompatible"]}

    workdir = Path(user_cfg.workdir)
    # running_inputs accumulates both user-provided values and prior-stage output paths
    running_inputs: dict[str, str] = {k: str(v) for k, v in user_cfg.inputs.items()}
    stage_plans: list[StagePlan] = []
    completed_stage_ids: list[str] = []

    for ps in preset.stages:
        if ps.skip:
            log.info(f"SKIP  {ps.stage_id}  ({ps.reason})")
            continue
        assert ps.tool_id is not None

        if ps.tool_id not in tools_by_id:
            raise ValueError(
                f"Preset '{preset_name}' references unknown tool '{ps.tool_id}' "
                f"at stage {ps.stage_id}"
            )

        if ps.tool_id in bad_ids:
            log.warning(
                f"WARN  {ps.stage_id}  tool={ps.tool_id} is INCOMPATIBLE with "
                f"this host's hardware — run may fail"
            )
        elif ps.tool_id in slow_ids:
            log.warning(
                f"WARN  {ps.stage_id}  tool={ps.tool_id} may run SLOWLY "
                f"(below recommended resources)"
            )

        stage_dir = _stage_dir(workdir, ps.stage_id)

        # Build per-stage params: chain outputs from prior stages
        stage_params = dict(ps.params)  # start with any preset-level overrides
        stage_params.update(
            _chain_artifact_params(
                stage_id=ps.stage_id,
                tool_id=ps.tool_id,
                completed_stage_ids=completed_stage_ids,
                workdir=workdir,
                running_inputs=running_inputs,
            )
        )

        stage_plans.append(
            StagePlan(stage_id=ps.stage_id, tool_id=ps.tool_id, params=stage_params)
        )

        # After this stage runs, its outputs become available as inputs
        artifacts = _artifact_paths(ps.stage_id, ps.tool_id, stage_dir, running_inputs)
        running_inputs.update(artifacts)
        completed_stage_ids.append(ps.stage_id)

    return ExecutionPlan(
        pipeline=preset.pipeline,
        preset=preset_name,
        species=user_cfg.species,
        read_type=user_cfg.read_type,
        mode=user_cfg.mode,
        inputs=dict(running_inputs),
        stages=stage_plans,
        workdir=workdir,
        registry_dir=user_cfg.registry_dir,
    )


def _chain_artifact_params(
    *,
    stage_id: str,
    tool_id: str,
    completed_stage_ids: list[str],
    workdir: Path,
    running_inputs: dict,
) -> dict[str, str]:
    """Determine path-override params for this stage from prior stage outputs.

    Logic:
    - step2 (assembly)      ← use clean reads produced by step1 if available
    - step3 (asm QC)        ← use assembly_fasta from step2
    - step4 (repeat mask)   ← use assembly_fasta from step2
    - step5 (struct annot)  ← use masked_assembly_fasta from step4 if available,
                               otherwise assembly_fasta from step2
    - step6 (func annot)    ← use protein_faa from step5
    - rnaseq step2          ← use clean reads from step1
    - rnaseq step3          ← use count_matrix from step2
    - rnaseq step4          ← use deg_table from step3
    """
    params: dict[str, str] = {}

    def _get(key: str) -> Optional[str]:
        return running_inputs.get(key)

    # Genome assembly
    if stage_id == "genome_assembly.step2":
        if _get("r1") and "genome_assembly.step1" in completed_stage_ids:
            params["r1"] = running_inputs["r1"]
            params["r2"] = running_inputs["r2"]

    elif stage_id in ("genome_assembly.step3",):
        if _get("assembly_fasta"):
            params["assembly_fasta"] = running_inputs["assembly_fasta"]

    elif stage_id == "genome_assembly.step4":
        if _get("assembly_fasta"):
            params["assembly_fasta"] = running_inputs["assembly_fasta"]

    elif stage_id == "genome_assembly.step5":
        src = _get("masked_assembly_fasta") or _get("assembly_fasta")
        if src:
            params["assembly_fasta"] = src

    elif stage_id == "genome_assembly.step6":
        if _get("protein_faa"):
            params["protein_faa"] = running_inputs["protein_faa"]
        src = _get("masked_assembly_fasta") or _get("assembly_fasta")
        if src:
            params["assembly_fasta"] = src

    # RNA-seq DEG
    elif stage_id == "rnaseq_deg.step2":
        if _get("r1") and "rnaseq_deg.step1" in completed_stage_ids:
            params["r1"] = running_inputs["r1"]
            params["r2"] = running_inputs["r2"]

    elif stage_id == "rnaseq_deg.step3":
        if _get("count_matrix"):
            params["count_matrix"] = running_inputs["count_matrix"]

    elif stage_id == "rnaseq_deg.step4":
        if _get("deg_table"):
            params["deg_table"] = running_inputs["deg_table"]

    return params


def plan_from_config(config: Path) -> ExecutionPlan:
    """Load a previously saved full ExecutionPlan YAML (produced by `bioflow custom`)."""
    with config.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ExecutionPlan.model_validate(data)


def interactive_build(pipeline: str, out: Path) -> None:
    """Interactive `bioflow custom` tool-selection flow — implemented in step 8."""
    raise NotImplementedError("Implement in step 8 (custom mode).")
