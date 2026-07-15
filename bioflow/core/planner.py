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
    # ── Genome assembly ────────────────────────────────────────────────────
    # step1: short-read QC → clean paired FASTQ
    ("genome_assembly.step1", "fastp"):      {"r1": "clean_R1.fastq.gz",
                                              "r2": "clean_R2.fastq.gz"},
    ("genome_assembly.step1", "fastqc"):     {"r1": "clean_R1.fastq.gz",
                                              "r2": "clean_R2.fastq.gz"},
    # step1: long-read QC/filter → filtered single-end FASTQ
    ("genome_assembly.step1", "filtlong"):   {"r1_long": "filtered.fastq.gz"},
    ("genome_assembly.step1", "nanoplot"):   {},  # report only, no downstream artifact

    # step2: de-novo assemblers
    ("genome_assembly.step2", "spades"):     {"assembly_fasta": "scaffolds.fasta"},
    ("genome_assembly.step2", "hifiasm"):    {"assembly_fasta": "asm.bp.p_ctg.fa"},
    ("genome_assembly.step2", "flye"):       {"assembly_fasta": "assembly.fasta"},
    ("genome_assembly.step2", "unicycler"):  {"assembly_fasta": "assembly.fasta"},
    # step2: resequencing
    ("genome_assembly.step2", "bwa_mem2"):   {"assembly_fasta": "consensus.fasta"},

    # step3: assembly QC (output is a report — not chained further)
    ("genome_assembly.step3", "quast"):      {"assembly_qc_report": "report.html"},
    ("genome_assembly.step3", "busco"):      {"assembly_qc_report": "short_summary.txt"},
    ("genome_assembly.step3", "checkm2"):    {"assembly_qc_report": "quality_report.tsv"},
    ("genome_assembly.step3", "merqury"):    {"assembly_qc_report": "merqury.qv"},

    # step4: repeat masking → masked FASTA  (also exposes repeat_library)
    ("genome_assembly.step4", "earlgrey"):        {"masked_assembly_fasta": "genome.masked.fasta",
                                                    "repeat_library": "repeats.fasta"},
    ("genome_assembly.step4", "repeatmasker"):    {"masked_assembly_fasta": "genome.masked.fasta"},
    ("genome_assembly.step4", "repeatmodeler"):   {"repeat_library": "consensi.fa.classified"},

    # step5: structural annotation → GFF + protein FASTA
    #   Integrated pipelines (prokka/bakta/dfast for bacteria, braker3 for
    #   eukaryotes) and ab-initio gene predictors (prodigal for bacteria,
    #   glimmerhmm/snap for eukaryotes) are interchangeable here — `bioflow
    #   custom` offers whichever is applicable to the chosen species.
    ("genome_assembly.step5", "prokka"):     {"structural_gff": "{sample_id}.gff",
                                              "protein_faa":    "{sample_id}.faa"},
    ("genome_assembly.step5", "bakta"):      {"structural_gff": "{sample_id}.gff",
                                              "protein_faa":    "{sample_id}.faa"},
    ("genome_assembly.step5", "dfast"):      {"structural_gff": "genome.gff",
                                              "protein_faa":    "protein.faa"},
    ("genome_assembly.step5", "prodigal"):   {"structural_gff": "genes.gff",
                                              "protein_faa":    "proteins.faa"},
    ("genome_assembly.step5", "braker3"):    {"structural_gff": "braker.gff3",
                                              "protein_faa":    "braker.aa"},
    ("genome_assembly.step5", "glimmerhmm"): {"structural_gff": "genes.gff"},
    ("genome_assembly.step5", "snap"):       {"structural_gff": "genes.gff"},

    # step6: functional annotation
    ("genome_assembly.step6", "eggnog_mapper"):   {"func_annotation_tsv": "annotations.tsv"},
    ("genome_assembly.step6", "interproscan"):    {"func_annotation_tsv": "annotations.tsv"},

    # ── RNA-seq DEG ─────────────────────────────────────────────────────────
    # step1: QC → clean paired FASTQ (long-read RNA-seq not yet supported)
    ("rnaseq_deg.step1", None):              {"r1": "clean_R1.fastq.gz",
                                              "r2": "clean_R2.fastq.gz"},

    # step2: alignment / quantification → count matrix
    ("rnaseq_deg.step2", "salmon"):          {"count_matrix": "quant.sf"},
    ("rnaseq_deg.step2", "kallisto"):        {"count_matrix": "abundance.tsv"},
    ("rnaseq_deg.step2", "hisat2"):          {"alignment_bam": "aligned.bam",
                                              "count_matrix":  "counts.tsv"},
    ("rnaseq_deg.step2", "star"):            {"alignment_bam": "Aligned.sortedByCoord.out.bam",
                                              "count_matrix":  "ReadsPerGene.out.tab"},

    # step3: DEG → results table
    ("rnaseq_deg.step3", None):              {"deg_table": "deg_results.tsv"},

    # step4: enrichment → HTML report
    ("rnaseq_deg.step4", None):              {"enrichment_report": "enrichment_report.html"},

    # ── Metagenomics ─────────────────────────────────────────────────────────
    ("metagenomics.step1", None):            {"r1": "clean_R1.fastq.gz",
                                              "r2": "clean_R2.fastq.gz"},
    ("metagenomics.step2", "kneaddata"):     {"r1_clean": "kneaddata_paired_1.fastq.gz",
                                              "r2_clean": "kneaddata_paired_2.fastq.gz"},
    ("metagenomics.step2", None):            {"r1_clean": "host_removed_R1.fastq.gz",
                                              "r2_clean": "host_removed_R2.fastq.gz"},
    ("metagenomics.step3", "kraken2"):       {"taxonomy_report": "kraken2_report.txt"},
    ("metagenomics.step3", "bracken"):       {"taxonomy_report": "bracken_output.txt",
                                              "taxonomy_table":  "bracken_abundance.tsv"},
    ("metagenomics.step3", "metaphlan4"):    {"taxonomy_report": "metaphlan_profile.tsv",
                                              "taxonomy_table":  "metaphlan_profile.tsv"},
    ("metagenomics.step4", "humann3"):       {"functional_profile": "pathcoverage.tsv",
                                              "gene_families":      "genefamilies.tsv"},
    ("metagenomics.step5", None):            {"diff_taxa_report": "lefse_results.res"},

    # ── Single-cell RNA-seq ──────────────────────────────────────────────────
    ("scrna_seq.step1", "cellranger"):       {"count_matrix_dir": "outs/filtered_feature_bc_matrix"},
    ("scrna_seq.step1", "starsolo"):         {"count_matrix_dir": "Solo.out/GeneFull/filtered"},
    ("scrna_seq.step2", "scanpy"):           {"filtered_h5ad":    "filtered.h5ad"},
    ("scrna_seq.step2", "seurat"):           {"seurat_rds":        "seurat_object.rds",
                                              "filtered_h5ad":     "filtered.h5ad"},
    ("scrna_seq.step3", "scanpy"):           {"clustered_h5ad":   "analyzed.h5ad"},
    ("scrna_seq.step3", "seurat"):           {"clustered_rds":     "seurat_clustered.rds"},
    ("scrna_seq.step4", "scanpy"):           {"markers_tsv":       "markers.tsv"},
    ("scrna_seq.step4", "seurat"):           {"markers_tsv":       "markers.csv"},
    ("scrna_seq.step5", "monocle3"):         {"trajectory_rds":    "monocle3_cds.rds"},

    # ── ChIP-seq ─────────────────────────────────────────────────────────────
    ("chip_seq.step1", None):               {"r1": "trimmed_R1.fastq.gz",
                                              "r2": "trimmed_R2.fastq.gz"},
    ("chip_seq.step2", "bowtie2"):           {"alignment_bam": "aligned.bam"},
    ("chip_seq.step3", "macs3"):             {"peaks_bed":     "{sample_id}_peaks.narrowPeak",
                                              "peaks_bdg":     "{sample_id}_treat_pileup.bdg"},
    ("chip_seq.step4", "deeptools"):         {"bigwig":        "{sample_id}.bw",
                                              "heatmap_pdf":   "heatmap.pdf"},
    ("chip_seq.step4", "homer"):             {"annotated_peaks": "annotated_peaks.txt"},
    ("chip_seq.step5", "homer"):             {"motif_report":  "motifs/knownResults.html"},

    # ── ATAC-seq ─────────────────────────────────────────────────────────────
    ("atac_seq.step1", None):               {"r1": "trimmed_R1.fastq.gz",
                                              "r2": "trimmed_R2.fastq.gz"},
    ("atac_seq.step2", "bowtie2"):           {"alignment_bam": "aligned.bam"},
    ("atac_seq.step3", "macs3"):             {"peaks_bed":     "{sample_id}_peaks.narrowPeak"},
    ("atac_seq.step4", "deeptools"):         {"bigwig":        "{sample_id}.bw",
                                              "diff_peaks":    "diff_peaks.tsv"},
    ("atac_seq.step5", "tobias"):            {"footprints_bw": "footprints.bw",
                                              "motif_report":  "motif_report.pdf"},
    ("atac_seq.step5", "homer"):             {"motif_report":  "motifs/knownResults.html"},

    # ── Bisulfite Methylation ─────────────────────────────────────────────────
    ("methylation.step1", None):             {"r1": "trimmed_R1.fastq.gz",
                                              "r2": "trimmed_R2.fastq.gz"},
    ("methylation.step2", "bismark"):        {"bismark_bam":          "aligned.bam",
                                              "methylation_coverage":  "CpG_report.txt.gz"},
    ("methylation.step3", None):             {"methylation_coverage":  "CpG_coverage.bismark.gz",
                                              "methylation_files":     "methylation_calls.txt"},
    ("methylation.step4", "methylkit"):      {"dmr_results":           "dmr_results.csv"},

    # ── Proteomics (LC-MS/MS) ────────────────────────────────────────────────
    # msconvert writes .mzML files into its stage dir — the dir itself is the artifact
    ("proteomics.step1", "msconvert"):       {"mzml_dir": ""},
    ("proteomics.step2", "msfragger"):       {"psm_tsv":  "psm.tsv"},
    ("proteomics.step3", "percolator"):      {"filtered_psm": "percolator.psms.xml"},
    ("proteomics.step4", "fragpipe"):        {"quant_matrix": "combined_protein.tsv"},
    ("proteomics.step4", "maxquant"):        {"quant_matrix": "proteinGroups.txt"},
    ("proteomics.step5", None):             {"protein_diff": "protein_diff.tsv"},
}


def _stage_dir(workdir: Path, stage_id: str) -> Path:
    return workdir / stage_id.replace(".", "_")


def _resolve_filename(filename: str, user_inputs: dict) -> str:
    """Expand {sample_id} and similar user-provided tokens in filenames.

    If a placeholder cannot be resolved, the raw filename is returned verbatim
    and a warning is emitted so the user knows the artifact path is incomplete.
    """
    try:
        return filename.format(**user_inputs)
    except KeyError as exc:
        log.warning(
            f"Artifact filename '{filename}' contains unresolved placeholder {exc}. "
            "Provide the missing key in the config inputs section."
        )
        return filename


def _artifact_paths(
    stage_id: str,
    tool_id: str,
    stage_dir: Path,
    user_inputs: dict,
) -> dict[str, str]:
    """Return {param_key: absolute_path} for the standard outputs of a stage.

    An empty-string filename means the stage directory itself is the artifact
    (used for tools that write multiple files to their output dir, e.g. msconvert).
    """
    result: dict[str, str] = {}
    for key in [(stage_id, tool_id), (stage_id, None)]:
        if key in _ARTIFACT_FILENAMES:
            for param, fname in _ARTIFACT_FILENAMES[key].items():
                if fname == "":
                    result[param] = str(stage_dir)
                else:
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
        if ps.tool_id is None:
            raise ValueError(
                f"Preset '{preset_name}' stage '{ps.stage_id}' has no tool_id "
                "and skip=false. Add a tool_id or set skip: true."
            )

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

    # Default empty for optional tool-specific placeholders so they don't leak
    # into the rendered command as literal {key} text when the user has not
    # supplied them.  Each tool's command line treats an empty value as "off".
    if tool_id == "spades":
        params.setdefault("extra_args", "")
    if tool_id == "clusterprofiler":
        params.setdefault("kegg_organism", "")

    # FastQC (step1 of multiple pipelines) takes a list of input FASTQ files.
    # Its template uses {inputs} — assemble it from the user's r1/r2 inputs.
    if tool_id == "fastqc":
        r1 = _get("r1")
        r2 = _get("r2")
        if r1:
            params["inputs"] = f"{r1} {r2}" if r2 else r1
        else:
            # No raw inputs registered yet — fall back to empty string so the
            # placeholder doesn't leak into the rendered command.
            params["inputs"] = ""

    # Genome assembly
    if stage_id == "genome_assembly.step2":
        # Short-read assemblers (spades, unicycler, bwa_mem2)
        if _get("r1") and "genome_assembly.step1" in completed_stage_ids:
            params["r1"] = running_inputs["r1"]
            if _get("r2"):
                params["r2"] = running_inputs["r2"]
        # Long-read assemblers (hifiasm, flye)
        if _get("r1_long") and "genome_assembly.step1" in completed_stage_ids:
            params["r1_long"] = running_inputs["r1_long"]

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
        # BRAKER3's template has a {rnaseq_bam_arg} slot — must always be
        # defined (defaulting to an empty string if no RNA-seq BAM is given).
        # If the user supplied rnaseq_bam, expand it into a CLI arg.
        if tool_id == "braker3":
            rnaseq_bam = _get("rnaseq_bam")
            params["rnaseq_bam_arg"] = (
                f"--bam={rnaseq_bam}" if rnaseq_bam else ""
            )

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
            # r2 may be absent for single-end RNA-seq libraries
            if _get("r2"):
                params["r2"] = running_inputs["r2"]

    elif stage_id == "rnaseq_deg.step3":
        if _get("count_matrix"):
            params["count_matrix"] = running_inputs["count_matrix"]

    elif stage_id == "rnaseq_deg.step4":
        if _get("deg_table"):
            params["deg_table"] = running_inputs["deg_table"]

    # ── Metagenomics ─────────────────────────────────────────────────────────
    elif stage_id == "metagenomics.step2":
        # Host removal uses clean reads from step1
        if _get("r1") and "metagenomics.step1" in completed_stage_ids:
            params["r1"] = running_inputs["r1"]
            if _get("r2"):
                params["r2"] = running_inputs["r2"]
        # bowtie2 template uses {index}; for host removal that's host_db
        if _get("host_db"):
            params["index"] = running_inputs["host_db"]

    elif stage_id == "metagenomics.step3":
        # Taxonomic profiling uses host-removed reads (or raw clean if no host removal)
        r1 = _get("r1_clean") or _get("r1")
        r2 = _get("r2_clean") or _get("r2")
        if r1:
            params["r1_clean"] = r1
            if r2:
                params["r2_clean"] = r2

    elif stage_id == "metagenomics.step4":
        # Functional profiling uses clean reads + taxonomy report
        r1 = _get("r1_clean") or _get("r1")
        if r1:
            params["r1_clean"] = r1
        if _get("taxonomy_report"):
            params["taxonomy_report"] = running_inputs["taxonomy_report"]

    elif stage_id == "metagenomics.step5":
        # Differential abundance uses taxonomy table
        if _get("taxonomy_table"):
            params["taxonomy_table"] = running_inputs["taxonomy_table"]

    # ── Single-cell RNA-seq ──────────────────────────────────────────────────
    elif stage_id == "scrna_seq.step2":
        if _get("count_matrix_dir"):
            params["count_matrix_dir"] = running_inputs["count_matrix_dir"]

    elif stage_id == "scrna_seq.step3":
        h5ad = _get("filtered_h5ad") or _get("count_matrix_dir")
        rds  = _get("seurat_rds")
        if h5ad:
            params["count_matrix_dir"] = h5ad
        if rds:
            params["seurat_rds"] = rds

    elif stage_id == "scrna_seq.step4":
        for key in ("clustered_h5ad", "clustered_rds", "filtered_h5ad", "seurat_rds"):
            if _get(key):
                params[key] = running_inputs[key]
                break

    elif stage_id == "scrna_seq.step5":
        for key in ("clustered_h5ad", "clustered_rds"):
            if _get(key):
                params[key] = running_inputs[key]
        if _get("count_matrix_dir"):
            params["count_matrix_dir"] = running_inputs["count_matrix_dir"]

    # ── ChIP-seq ─────────────────────────────────────────────────────────────
    elif stage_id == "chip_seq.step2":
        if _get("r1") and "chip_seq.step1" in completed_stage_ids:
            params["r1"] = running_inputs["r1"]
            if _get("r2"):
                params["r2"] = running_inputs["r2"]
        # bowtie2 template uses {index} — wire from user's bowtie2_index input
        if _get("bowtie2_index"):
            params["index"] = running_inputs["bowtie2_index"]

    elif stage_id == "chip_seq.step3":
        if _get("alignment_bam"):
            params["alignment_bam"] = running_inputs["alignment_bam"]
        # MACS3 template uses {control_arg} — expand to "-c <bam>" when a
        # control BAM is provided, empty string otherwise (no-control mode).
        control = _get("control_bam")
        params["control_arg"] = f"-c {control}" if control else ""

    elif stage_id == "chip_seq.step4":
        if _get("alignment_bam"):
            params["alignment_bam"] = running_inputs["alignment_bam"]
        if _get("peaks_bed"):
            params["peaks_bed"] = running_inputs["peaks_bed"]

    elif stage_id == "chip_seq.step5":
        if _get("peaks_bed"):
            params["peaks_bed"] = running_inputs["peaks_bed"]

    # ── ATAC-seq ─────────────────────────────────────────────────────────────
    elif stage_id == "atac_seq.step2":
        if _get("r1") and "atac_seq.step1" in completed_stage_ids:
            params["r1"] = running_inputs["r1"]
            if _get("r2"):
                params["r2"] = running_inputs["r2"]
        if _get("bowtie2_index"):
            params["index"] = running_inputs["bowtie2_index"]

    elif stage_id == "atac_seq.step3":
        if _get("alignment_bam"):
            params["alignment_bam"] = running_inputs["alignment_bam"]
        # ATAC-seq never uses a control sample → empty control_arg
        params["control_arg"] = ""

    elif stage_id == "atac_seq.step4":
        if _get("alignment_bam"):
            params["alignment_bam"] = running_inputs["alignment_bam"]
        if _get("peaks_bed"):
            params["peaks_bed"] = running_inputs["peaks_bed"]

    elif stage_id == "atac_seq.step5":
        if _get("alignment_bam"):
            params["alignment_bam"] = running_inputs["alignment_bam"]
        if _get("peaks_bed"):
            params["peaks_bed"] = running_inputs["peaks_bed"]

    # ── Bisulfite Methylation ─────────────────────────────────────────────────
    elif stage_id == "methylation.step2":
        if _get("r1") and "methylation.step1" in completed_stage_ids:
            params["r1"] = running_inputs["r1"]
            if _get("r2"):
                params["r2"] = running_inputs["r2"]

    elif stage_id == "methylation.step3":
        if _get("bismark_bam"):
            params["bismark_bam"] = running_inputs["bismark_bam"]

    elif stage_id == "methylation.step4":
        if _get("methylation_coverage"):
            params["methylation_coverage"] = running_inputs["methylation_coverage"]
        if _get("methylation_files"):
            params["methylation_files"] = running_inputs["methylation_files"]

    # ── Proteomics ────────────────────────────────────────────────────────────
    elif stage_id == "proteomics.step2":
        if _get("mzml_dir"):
            params["mzml_dir"] = running_inputs["mzml_dir"]

    elif stage_id == "proteomics.step3":
        if _get("psm_tsv"):
            params["psm_tsv"] = running_inputs["psm_tsv"]

    elif stage_id == "proteomics.step4":
        if _get("filtered_psm"):
            params["filtered_psm"] = running_inputs["filtered_psm"]
        if _get("mzml_dir"):
            params["mzml_dir"] = running_inputs["mzml_dir"]

    elif stage_id == "proteomics.step5":
        if _get("quant_matrix"):
            params["quant_matrix"] = running_inputs["quant_matrix"]

    return params


def plan_from_config(config: Path) -> ExecutionPlan:
    """Load a previously saved full ExecutionPlan YAML (produced by `bioflow custom`)."""
    with config.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ExecutionPlan.model_validate(data)


# ---------------------------------------------------------------------------
# Interactive custom-mode helpers
# ---------------------------------------------------------------------------

# Canonical ordered stage list for each pipeline.
# Tuple: (stage_id, human_label, is_optional)
_PIPELINE_STAGES: dict[str, list[tuple[str, str, bool]]] = {
    "genome_assembly": [
        ("genome_assembly.step1", "Read QC",                False),
        ("genome_assembly.step2", "Assembly",               False),
        ("genome_assembly.step3", "Assembly QC",            False),
        ("genome_assembly.step4", "Repeat Masking",         True),   # optional for prokaryote
        ("genome_assembly.step5", "Structural Annotation",  False),
        ("genome_assembly.step6", "Functional Annotation",  False),
    ],
    "rnaseq_deg": [
        ("rnaseq_deg.step1", "RNA-seq QC",                  False),
        ("rnaseq_deg.step2", "Alignment / Quantification",  False),
        ("rnaseq_deg.step3", "DEG Analysis",                False),
        ("rnaseq_deg.step4", "Enrichment Analysis",         False),
    ],
    "metagenomics": [
        ("metagenomics.step1", "Read QC",                   False),
        ("metagenomics.step2", "Host Removal",              True),   # optional for non-host samples
        ("metagenomics.step3", "Taxonomic Profiling",       False),
        ("metagenomics.step4", "Functional Profiling",      True),   # optional
        ("metagenomics.step5", "Differential Abundance",    True),   # optional
    ],
    "scrna_seq": [
        ("scrna_seq.step1", "Demux / Alignment",            False),
        ("scrna_seq.step2", "QC & Filtering",               False),
        ("scrna_seq.step3", "Clustering & Dim. Reduction",  False),
        ("scrna_seq.step4", "Marker Gene / DEG",            False),
        ("scrna_seq.step5", "Trajectory / Pseudotime",      True),   # optional
    ],
    "chip_seq": [
        ("chip_seq.step1",  "Read QC & Trimming",           False),
        ("chip_seq.step2",  "Alignment",                    False),
        ("chip_seq.step3",  "Peak Calling",                 False),
        ("chip_seq.step4",  "Peak Annotation / Coverage",   False),
        ("chip_seq.step5",  "Motif Analysis",               True),   # optional
    ],
    "atac_seq": [
        ("atac_seq.step1",  "Read QC & Trimming",           False),
        ("atac_seq.step2",  "Alignment",                    False),
        ("atac_seq.step3",  "Peak Calling",                 False),
        ("atac_seq.step4",  "Coverage & Differential",      False),
        ("atac_seq.step5",  "Footprinting & Motif",         True),   # optional
    ],
    "methylation": [
        ("methylation.step1", "Read QC & Trimming",         False),
        ("methylation.step2", "Bisulfite Alignment",        False),
        ("methylation.step3", "Methylation Extraction",     False),
        ("methylation.step4", "DMR Analysis",               True),   # optional
    ],
    "proteomics": [
        ("proteomics.step1", "Format Conversion",           False),
        ("proteomics.step2", "Database Search",             False),
        ("proteomics.step3", "FDR Control",                 False),
        ("proteomics.step4", "Quantification",              False),
        ("proteomics.step5", "Statistical Analysis",        True),   # optional
    ],
}

# Required input keys per (pipeline, read_type).
# Each entry: (key, human_description)
_REQUIRED_INPUTS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("genome_assembly", "short"): [
        ("sample_id",     "Sample identifier (e.g. ecoli_test)"),
        ("reference_genome","Reference FASTA (only required for resequencing/bwa_mem2 mode)"),
        ("r1",            "Read 1 FASTQ path"),
        ("r2",            "Read 2 FASTQ path"),
        # step4/5 optional keys — required only when the chosen tool needs them
        ("bakta_db_dir",  "Bakta DB directory (only if using Bakta for annotation)"),
        ("repeat_species","Repeat library species (only if using EarlGrey, e.g. 'Insecta')"),
        ("eggnog_db_dir", "eggNOG database directory"),
    ],
    ("genome_assembly", "long_hifi"): [
        ("sample_id",     "Sample identifier"),
        ("r1_long",       "Long-read (HiFi) FASTQ path"),
        ("busco_lineage", "BUSCO lineage dataset (e.g. insecta_odb10)"),
        ("genome_size",   "Estimated genome size (e.g. 130m)"),
        ("eggnog_db_dir", "eggNOG database directory"),
        ("bakta_db_dir",  "Bakta DB directory (only if using Bakta)"),
        ("repeat_species","Repeat library species (only if using EarlGrey, e.g. 'Insecta')"),
    ],
    ("genome_assembly", "long_ont"): [
        ("sample_id",     "Sample identifier"),
        ("r1_long",       "Long-read (ONT) FASTQ path"),
        ("eggnog_db_dir", "eggNOG database directory"),
        ("bakta_db_dir",  "Bakta DB directory (only if using Bakta)"),
        ("repeat_species","Repeat library species (only if using EarlGrey)"),
    ],
    ("genome_assembly", "hybrid"): [
        ("sample_id",     "Sample identifier"),
        ("r1",            "Short Read 1 FASTQ path"),
        ("r2",            "Short Read 2 FASTQ path"),
        ("r1_long",       "Long-read FASTQ path"),
        ("eggnog_db_dir", "eggNOG database directory"),
        ("bakta_db_dir",  "Bakta DB directory (only if using Bakta)"),
        ("repeat_species","Repeat library species (only if using EarlGrey)"),
    ],
    ("rnaseq_deg", "short"): [
        ("sample_id",        "Sample identifier"),
        ("sample_sheet",     "Sample sheet CSV path"),
        ("reference_genome", "Reference genome FASTA path"),
        ("annotation_gtf",   "Annotation GTF path"),
    ],
    # Metagenomics
    ("metagenomics", "short"): [
        ("sample_id",         "Sample identifier"),
        ("sample_sheet",      "Sample sheet CSV path (sample_id, fastq_r1, fastq_r2, group)"),
        ("host_db",           "Host genome Bowtie2 index for KneadData (leave blank to skip host removal)"),
        ("kraken2_db",        "Kraken2 database directory"),
        ("read_length",       "Read length for Bracken (e.g. 150)"),
        ("bracken_threshold", "Bracken minimum hit threshold (e.g. 10)"),
        ("metaphlan_db",      "MetaPhlAn4 database directory (optional, leave blank if using Kraken2)"),
        ("chocophlan_db",     "HUMAnN3 ChocoPhlAn DB directory (optional)"),
        ("uniref_db",         "HUMAnN3 UniRef DB directory (optional)"),
    ],
    # Single-cell RNA-seq (10x Chromium)
    ("scrna_seq", "short"): [
        ("sample_id",       "Sample identifier"),
        ("fastq_dir",       "Directory containing FASTQ files"),
        ("cellranger_ref",  "Cell Ranger reference transcriptome directory"),
        ("star_index",      "STAR genome index directory (alternative to Cell Ranger)"),
        ("whitelist",       "Cell barcode whitelist (10x v3: 3M-february-2018.txt.gz)"),
        ("expected_cells",  "Expected number of cells (e.g. 5000)"),
    ],
    # ChIP-seq
    ("chip_seq", "short"): [
        ("sample_id",       "Sample identifier"),
        ("sample_sheet",    "Sample sheet CSV (sample_id, fastq_r1, fastq_r2, control_id, mark)"),
        ("reference_genome","Reference genome FASTA path"),
        ("bowtie2_index",   "Bowtie2 genome index prefix"),
        ("genome_size",     "Effective genome size (hs/mm/ce/dm or integer)"),
        ("annotation_gtf",  "Gene annotation GTF path"),
        ("control_bam",     "Control/Input BAM for MACS3 (leave blank if none)"),
    ],
    # ATAC-seq
    ("atac_seq", "short"): [
        ("sample_id",       "Sample identifier"),
        ("sample_sheet",    "Sample sheet CSV (sample_id, fastq_r1, fastq_r2, group)"),
        ("reference_genome","Reference genome FASTA path"),
        ("bowtie2_index",   "Bowtie2 genome index prefix"),
        ("genome_size",     "Effective genome size (hs/mm/ce/dm or integer)"),
        ("annotation_gtf",  "Gene annotation GTF (only required when running HOMER step5)"),
    ],
    # Bisulfite-seq / WGBS
    ("methylation", "short"): [
        ("sample_id",       "Sample identifier"),
        ("sample_sheet",    "Sample sheet CSV (sample_id, fastq_r1, fastq_r2, condition)"),
        ("bismark_genome",  "Bismark-prepared genome directory"),
        ("genome_build",    "Genome assembly name (e.g. hg38, mm10)"),
        ("sample_ids",      "Comma-separated sample IDs matching sample_sheet"),
        ("methylation_files", "Comma-separated methylation coverage files (after Bismark)"),
    ],
    # Proteomics (DDA)
    ("proteomics", "ms_dda"): [
        ("sample_id",          "Experiment identifier"),
        ("raw_file_dir",       "Directory containing raw mass-spec files (.raw/.d/.wiff)"),
        ("protein_db",         "FASTA protein database for database search"),
        ("msfragger_params",   "MSFragger parameter file (.params)"),
        ("fragpipe_workflow",  "FragPipe workflow file (.workflow)"),
        ("manifest_file",      "FragPipe manifest file listing mzML paths"),
        ("maxquant_params_xml","MaxQuant mqpar.xml (only if using MaxQuant)"),
    ],
    # Proteomics (DIA)
    ("proteomics", "ms_dia"): [
        ("sample_id",          "Experiment identifier"),
        ("raw_file_dir",       "Directory containing raw DIA files"),
        ("protein_db",         "FASTA protein database"),
        ("fragpipe_workflow",  "FragPipe DIA workflow file"),
        ("manifest_file",      "FragPipe manifest file"),
        ("maxquant_params_xml","MaxQuant mqpar.xml (only if using MaxQuant)"),
    ],
}


def _required_inputs_for(pipeline: str, read_type: str) -> list[tuple[str, str]]:
    return _REQUIRED_INPUTS.get(
        (pipeline, read_type),
        [("sample_id", "Sample identifier")],
    )


def interactive_build(pipeline: str, out: Path, *, registry_dir: Path = Path("registry")) -> None:
    """Interactive ``bioflow custom`` tool-selection flow.

    Uses *questionary* to prompt the user for:
      1. Pipeline metadata (species, read_type, mode, workdir)
      2. Per-stage tool selection (only applicable + hw-compatible tools shown)
      3. Required input paths

    The resulting :class:`ExecutionPlan` is serialised as YAML to *out*.
    """
    # Validate pipeline name early (before any import of questionary)
    if pipeline not in _PIPELINE_STAGES:
        raise ValueError(
            f"Unknown pipeline '{pipeline}'. Available: {list(_PIPELINE_STAGES)}"
        )

    try:
        import questionary  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "questionary is required for interactive mode: pip install questionary"
        ) from exc

    from rich.console import Console  # noqa: PLC0415

    from bioflow.core.compatibility import classify, filter_applicable  # noqa: PLC0415

    console = Console()

    console.print(f"\n[bold cyan]bioflow custom — {pipeline}[/]\n")

    # ── 1. Gather pipeline metadata ──────────────────────────────────────────
    # Species choices depend on the pipeline type
    _OMICS_PIPELINES = {"metagenomics", "scrna_seq", "chip_seq", "atac_seq", "methylation", "proteomics"}
    if pipeline in _OMICS_PIPELINES:
        species = questionary.select(
            "Species type:",
            choices=["any", "eukaryote", "prokaryote", "eukaryote_small"],
        ).ask()
    else:
        species = questionary.select(
            "Species type:",
            choices=["prokaryote", "eukaryote", "eukaryote_small"],
        ).ask()
    if species is None:
        raise KeyboardInterrupt

    _READ_TYPE_CHOICES: dict[str, list[str]] = {
        "genome_assembly": ["short", "long_hifi", "long_ont", "hybrid"],
        "rnaseq_deg":      ["short"],
        "metagenomics":    ["short"],
        "scrna_seq":       ["short"],
        "chip_seq":        ["short"],
        "atac_seq":        ["short"],
        "methylation":     ["short"],
        "proteomics":      ["ms_dda", "ms_dia"],
    }
    read_type = questionary.select(
        "Read type / data type:",
        choices=_READ_TYPE_CHOICES.get(pipeline, ["short"]),
    ).ask()
    if read_type is None:
        raise KeyboardInterrupt

    _MODE_CHOICES: dict[str, list[str]] = {
        "genome_assembly": ["de_novo", "resequencing"],
        "rnaseq_deg":      ["de_novo"],
        "metagenomics":    ["profiling"],
        "scrna_seq":       ["de_novo"],
        "chip_seq":        ["peak_calling"],
        "atac_seq":        ["peak_calling", "differential"],
        "methylation":     ["wgbs", "rrbs"],
        "proteomics":      ["dda", "dia"],
    }
    mode = questionary.select(
        "Analysis mode:",
        choices=_MODE_CHOICES.get(pipeline, ["de_novo"]),
    ).ask()
    if mode is None:
        raise KeyboardInterrupt

    workdir_str = questionary.text(
        "Output working directory:",
        default="./output",
    ).ask()
    if workdir_str is None:
        raise KeyboardInterrupt
    workdir_path = Path(workdir_str)

    reg_str = questionary.text(
        "Registry directory:",
        default=str(registry_dir),
    ).ask()
    if reg_str is None:
        raise KeyboardInterrupt
    registry_dir = Path(reg_str)

    # ── 2. Load tools + hardware ─────────────────────────────────────────────
    tools = load_registry(registry_dir)
    hw = detect()
    classified = classify(tools, hw)

    slow_ids: set[str] = {t.id for t in classified["runnable_slow"]}
    bad_ids:  set[str] = {t.id for t in classified["incompatible"]}

    if bad_ids:
        console.print(
            f"[red]⚠ {len(bad_ids)} tool(s) incompatible with this host:[/] "
            + ", ".join(sorted(bad_ids))
        )
    if slow_ids:
        console.print(
            f"[yellow]⚠ {len(slow_ids)} tool(s) may run slowly:[/] "
            + ", ".join(sorted(slow_ids))
        )

    # ── 3. Per-stage tool selection ──────────────────────────────────────────
    running_inputs: dict[str, str] = {}
    completed_stage_ids: list[str] = []
    stage_plans: list[StagePlan] = []

    for stage_id, stage_label, is_optional in _PIPELINE_STAGES[pipeline]:
        applicable = filter_applicable(
            tools,
            species=species,
            read_type=read_type,
            mode=mode,
            stage=stage_id,
        )

        if not applicable:
            console.print(
                f"[dim]  {stage_id} ({stage_label}): no applicable tools — skipping[/]"
            )
            continue

        console.print(f"\n[bold]Stage {stage_id}[/] — {stage_label}")

        # Build choice labels with HW status badges
        choices: list[questionary.Choice] = []
        for t in applicable:
            if t.id in bad_ids:
                label = f"{t.id}  [incompatible]"
            elif t.id in slow_ids:
                label = f"{t.id}  [slow]"
            else:
                label = t.id
            choices.append(questionary.Choice(title=label, value=t.id))

        if is_optional:
            choices.append(questionary.Choice(title="[skip this stage]", value="__skip__"))

        selected = questionary.select(
            f"Choose tool for '{stage_label}':",
            choices=choices,
        ).ask()

        if selected is None:
            raise KeyboardInterrupt
        if selected == "__skip__":
            log.info(f"SKIP  {stage_id}  (user skipped)")
            continue

        stage_dir = _stage_dir(workdir_path, stage_id)
        stage_params = _chain_artifact_params(
            stage_id=stage_id,
            tool_id=selected,
            completed_stage_ids=completed_stage_ids,
            workdir=workdir_path,
            running_inputs=running_inputs,
        )

        stage_plans.append(
            StagePlan(stage_id=stage_id, tool_id=selected, params=stage_params)
        )
        artifacts = _artifact_paths(stage_id, selected, stage_dir, running_inputs)
        running_inputs.update(artifacts)
        completed_stage_ids.append(stage_id)

    # ── 4. Gather required inputs ────────────────────────────────────────────
    console.print("\n[bold]Required inputs:[/]")
    inputs: dict[str, str] = {}
    for key, description in _required_inputs_for(pipeline, read_type):
        # For a BUSCO lineage, pre-fill a species-appropriate recommendation the
        # user can accept or override (bioflow lineage <taxon> for a finer pick).
        default = ""
        if key == "busco_lineage":
            from bioflow.core.lineage import recommend_lineage  # noqa: PLC0415
            rec = recommend_lineage(species=species)
            default = rec["lineage"]
            console.print(f"  [dim]recommended lineage for {species}: "
                          f"{rec['lineage']} — run `bioflow lineage <taxon>` "
                          f"for a more specific pick[/]")
        val = questionary.text(f"  {description} [{key}]:", default=default).ask()
        if val is None:
            raise KeyboardInterrupt
        if val:
            inputs[key] = val

    # ── 5. Build & persist ExecutionPlan ─────────────────────────────────────
    plan = ExecutionPlan(
        pipeline=pipeline,
        preset=None,
        species=species,
        read_type=read_type,
        mode=mode,
        inputs=inputs,
        stages=stage_plans,
        workdir=workdir_path,
        registry_dir=registry_dir,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        yaml.dump(plan.model_dump(mode="json"), fh, allow_unicode=True, sort_keys=False)

    console.print(
        f"\n[green]✓ Custom plan saved → {out}[/]  "
        f"({len(stage_plans)} active stages)"
    )
