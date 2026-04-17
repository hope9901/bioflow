"""E2E test: prokaryote de-novo short-read pipeline (MockBackend).

Runs the full 5-stage prokaryote_denovo_short preset through plan_from_preset
+ run_plan using MockBackend so no Docker is needed.

Verifications:
  - All 5 stages execute in order
  - Checkpoint file is written and marks all stages completed
  - Calling run_plan a second time skips all stages (resume behaviour)
  - generate_reports produces pipeline_summary.html
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REGISTRY_DIR  = Path(__file__).resolve().parents[2] / "registry"
TEST_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "test" / "ecoli_small"


def _cfg(tmp_path: Path) -> Path:
    cfg = {
        "pipeline": "genome_assembly",
        "species": "prokaryote",
        "read_type": "short",
        "mode": "de_novo",
        "inputs": {
            "sample_id": "ecoli_test",
            "r1": str(TEST_DATA_DIR / "R1.fastq.gz"),
            "r2": str(TEST_DATA_DIR / "R2.fastq.gz"),
        },
        "workdir": str(tmp_path / "wd"),
        "registry_dir": str(REGISTRY_DIR),
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy-path E2E
# ---------------------------------------------------------------------------

def test_prokaryote_short_all_stages_run(tmp_path):
    """All 5 active stages should execute via MockBackend."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("prokaryote_denovo_short", _cfg(tmp_path))
    assert len(plan.stages) == 5

    backend = MockBackend()
    run_plan(plan, backend=backend)

    assert len(backend.calls) == 5
    executed_tools = [c["image"].split("/")[-1].split(":")[0] for c in backend.calls]
    # All 5 tools must have been called
    assert len(executed_tools) == 5


def test_prokaryote_short_stages_run_in_order(tmp_path):
    """Stages must execute in preset order: fastp first, eggnog_mapper last."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("prokaryote_denovo_short", _cfg(tmp_path))
    backend = MockBackend()
    run_plan(plan, backend=backend)

    # Check order via the plan's stage list (stages match calls 1-to-1)
    assert len(backend.calls) == len(plan.stages)
    # fastp image first, eggnog_mapper image last
    assert "fastp" in backend.calls[0]["image"]
    assert "eggnog" in backend.calls[-1]["image"]


def test_prokaryote_short_checkpoint_written(tmp_path):
    """run_plan must create .bioflow_state.json with all stages marked completed."""
    from bioflow.core.checkpoint import load
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("prokaryote_denovo_short", _cfg(tmp_path))
    run_plan(plan, backend=MockBackend())

    state = load(plan.workdir)
    completed = state.get("completed_stages", [])
    for stage in plan.stages:
        assert stage.stage_id in completed, \
            f"{stage.stage_id} not in checkpoint completed list"


def test_prokaryote_short_resume_skips_completed(tmp_path):
    """Re-running an already-completed plan should produce 0 backend calls."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("prokaryote_denovo_short", _cfg(tmp_path))
    # First run
    run_plan(plan, backend=MockBackend())
    # Second run — all stages already checkpointed
    second_backend = MockBackend()
    run_plan(plan, backend=second_backend)
    assert len(second_backend.calls) == 0, \
        "Re-run should skip all completed stages"


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def test_prokaryote_short_generates_summary_html(tmp_path):
    """generate_reports(skip_multiqc=True) should produce pipeline_summary.html."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.report import generate_reports
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("prokaryote_denovo_short", _cfg(tmp_path))
    run_plan(plan, backend=MockBackend())

    result = generate_reports(plan, tmp_path / "reports", skip_multiqc=True)
    summary = result["summary"]

    assert summary is not None and summary.exists()
    content = summary.read_text(encoding="utf-8")
    assert "prokaryote" in content
    assert "prokaryote_denovo_short" in content
    # All stages present in HTML
    for stage in plan.stages:
        assert stage.tool_id in content
