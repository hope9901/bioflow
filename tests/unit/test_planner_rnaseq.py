"""Planner tests specific to RNA-seq DEG pipeline."""

from __future__ import annotations

from pathlib import Path

import yaml

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


def _write_rnaseq_config(tmp_path: Path) -> Path:
    cfg = {
        "pipeline": "rnaseq_deg",
        "species": "eukaryote",
        "read_type": "short",
        "mode": "de_novo",
        "inputs": {
            "r1": "/workspace/in/sample_R1.fastq.gz",
            "r2": "/workspace/in/sample_R2.fastq.gz",
            "sample_id": "hsa_ctrl_vs_treat",
            "reference_genome": "/refs/genomes/GRCh38.fa",
            "annotation_gtf": "/refs/genomes/GRCh38.gtf",
            "sample_sheet": "/workspace/in/samples.csv",
            "kegg_organism": "hsa",
        },
        "workdir": str(tmp_path / "out"),
        "registry_dir": str(REGISTRY_DIR),
    }
    p = tmp_path / "rnaseq_config.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


def test_rnaseq_preset_produces_four_stages(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_rnaseq_config(tmp_path)
    plan = plan_from_preset("rnaseq_deseq2_standard", cfg)

    assert plan.pipeline == "rnaseq_deg"
    assert len(plan.stages) == 4
    tool_ids = [s.tool_id for s in plan.stages]
    assert tool_ids == ["fastp", "salmon", "deseq2", "clusterprofiler"]


def test_step2_salmon_gets_clean_reads_from_step1(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_rnaseq_config(tmp_path)
    plan = plan_from_preset("rnaseq_deseq2_standard", cfg)
    workdir = plan.workdir

    salmon = next(s for s in plan.stages if s.tool_id == "salmon")
    expected_r1 = str(workdir / "rnaseq_deg_step1" / "clean_R1.fastq.gz")
    assert salmon.params.get("r1") == expected_r1


def test_step3_deseq2_gets_count_matrix_from_step2(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_rnaseq_config(tmp_path)
    plan = plan_from_preset("rnaseq_deseq2_standard", cfg)
    workdir = plan.workdir

    deseq2 = next(s for s in plan.stages if s.tool_id == "deseq2")
    # Salmon produces quant.sf as count_matrix
    expected = str(workdir / "rnaseq_deg_step2" / "quant.sf")
    assert deseq2.params.get("count_matrix") == expected


def test_step4_clusterprofiler_gets_deg_table_from_step3(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_rnaseq_config(tmp_path)
    plan = plan_from_preset("rnaseq_deseq2_standard", cfg)
    workdir = plan.workdir

    clust = next(s for s in plan.stages if s.tool_id == "clusterprofiler")
    expected = str(workdir / "rnaseq_deg_step3" / "deg_results.tsv")
    assert clust.params.get("deg_table") == expected


def test_rnaseq_plan_pipeline_mismatch_raises(tmp_path):
    """Preset for rnaseq_deg should reject a genome_assembly config."""
    import pytest
    from bioflow.core.planner import plan_from_preset

    # Write a genome_assembly config but try to use rnaseq preset
    cfg_data = {
        "pipeline": "genome_assembly",
        "species": "prokaryote",
        "read_type": "short",
        "mode": "de_novo",
        "inputs": {},
        "workdir": str(tmp_path / "out"),
        "registry_dir": str(REGISTRY_DIR),
    }
    cfg = tmp_path / "wrong_cfg.yaml"
    cfg.write_text(yaml.dump(cfg_data), encoding="utf-8")

    with pytest.raises(ValueError, match="pipeline"):
        plan_from_preset("rnaseq_deseq2_standard", cfg)
