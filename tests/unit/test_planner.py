"""Planner tests: preset loading, artifact chaining, skip handling."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_user_config(tmp_path: Path, *, registry_dir: Path = REGISTRY_DIR) -> Path:
    cfg = {
        "pipeline": "genome_assembly",
        "species": "prokaryote",
        "read_type": "short",
        "mode": "de_novo",
        "inputs": {
            "r1": "/workspace/in/sample_R1.fastq.gz",
            "r2": "/workspace/in/sample_R2.fastq.gz",
            "sample_id": "ecoli1",
            "eggnog_db_dir": "/refs/dbs/eggnog",
        },
        "workdir": str(tmp_path / "out"),
        "registry_dir": str(registry_dir),
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plan_from_preset_returns_execution_plan(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    plan = plan_from_preset("prokaryote_denovo_short", cfg)

    assert plan.pipeline == "genome_assembly"
    assert plan.preset == "prokaryote_denovo_short"
    assert plan.species == "prokaryote"


def test_preset_skip_removes_repeat_masking_stage(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    plan = plan_from_preset("prokaryote_denovo_short", cfg)

    stage_ids = [s.stage_id for s in plan.stages]
    assert "genome_assembly.step4" not in stage_ids, (
        "Repeat masking (step4) should be skipped for prokaryote"
    )


def test_preset_produces_five_active_stages(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    plan = plan_from_preset("prokaryote_denovo_short", cfg)

    # step1 fastp, step2 spades, step3 quast, step5 prokka, step6 eggnog_mapper
    assert len(plan.stages) == 5
    tool_ids = [s.tool_id for s in plan.stages]
    assert "fastp" in tool_ids
    assert "spades" in tool_ids
    assert "quast" in tool_ids
    assert "prokka" in tool_ids
    assert "eggnog_mapper" in tool_ids


def test_step2_receives_cleaned_reads_from_step1(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    plan = plan_from_preset("prokaryote_denovo_short", cfg)
    workdir = plan.workdir

    spades = next(s for s in plan.stages if s.tool_id == "spades")
    # After step1 (fastp) the cleaned reads live in its stage dir
    expected_r1 = str(workdir / "genome_assembly_step1" / "clean_R1.fastq.gz")
    assert spades.params.get("r1") == expected_r1


def test_step3_receives_assembly_fasta_from_step2(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    plan = plan_from_preset("prokaryote_denovo_short", cfg)
    workdir = plan.workdir

    quast = next(s for s in plan.stages if s.tool_id == "quast")
    expected = str(workdir / "genome_assembly_step2" / "scaffolds.fasta")
    assert quast.params.get("assembly_fasta") == expected


def test_step5_receives_assembly_fasta_directly_when_step4_skipped(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    plan = plan_from_preset("prokaryote_denovo_short", cfg)
    workdir = plan.workdir

    prokka = next(s for s in plan.stages if s.tool_id == "prokka")
    # step4 is skipped so prokka should receive step2's assembly
    expected = str(workdir / "genome_assembly_step2" / "scaffolds.fasta")
    assert prokka.params.get("assembly_fasta") == expected


def test_step6_receives_protein_faa_from_step5(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    plan = plan_from_preset("prokaryote_denovo_short", cfg)
    workdir = plan.workdir

    eggnog = next(s for s in plan.stages if s.tool_id == "eggnog_mapper")
    expected_faa = str(workdir / "genome_assembly_step5" / "ecoli1.faa")
    assert eggnog.params.get("protein_faa") == expected_faa


def test_unknown_preset_raises_file_not_found(tmp_path):
    from bioflow.core.planner import plan_from_preset

    cfg = _write_user_config(tmp_path)
    with pytest.raises(FileNotFoundError, match="not found"):
        plan_from_preset("this_preset_does_not_exist", cfg)


def test_plan_from_config_roundtrip(tmp_path):
    from bioflow.core.planner import ExecutionPlan, StagePlan, plan_from_config

    plan = ExecutionPlan(
        pipeline="genome_assembly",
        species="prokaryote",
        read_type="short",
        mode="de_novo",
        inputs={"r1": "/data/r1.fq.gz", "r2": "/data/r2.fq.gz", "sample_id": "s1"},
        stages=[
            StagePlan(stage_id="genome_assembly.step1", tool_id="fastp"),
            StagePlan(stage_id="genome_assembly.step2", tool_id="spades",
                      params={"r1": "/data/clean_r1.fq.gz"}),
        ],
        workdir=tmp_path / "out",
        registry_dir=REGISTRY_DIR,
    )
    cfg_path = tmp_path / "plan.yaml"
    cfg_path.write_text(
        yaml.dump(plan.model_dump(mode="json")), encoding="utf-8"
    )
    loaded = plan_from_config(cfg_path)
    assert loaded.pipeline == plan.pipeline
    assert len(loaded.stages) == 2
    assert loaded.stages[1].params["r1"] == "/data/clean_r1.fq.gz"
