"""Tests for stage failure tracking and HTML error display (items 4 & 5)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


def _make_plan(tmp_path: Path):
    from bioflow.core.planner import plan_from_preset
    cfg = {
        "pipeline": "genome_assembly", "species": "prokaryote",
        "read_type": "short", "mode": "de_novo",
        "inputs": {"sample_id": "t", "r1": "/r1.fq", "r2": "/r2.fq"},
        "workdir": str(tmp_path / "wd"),
        "registry_dir": str(REGISTRY_DIR),
    }
    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return plan_from_preset("prokaryote_denovo_short", p)


# ── checkpoint.mark_failed ────────────────────────────────────────────────

def test_mark_failed_records_error(tmp_path):
    from bioflow.core.checkpoint import load, mark_failed
    wd = tmp_path / "wd"; wd.mkdir()
    mark_failed(wd, "genome_assembly.step2", "exit_code=1", "stderr line")
    state = load(wd)
    assert "genome_assembly.step2" in state["failed_stages"]
    assert state["failed_stages"]["genome_assembly.step2"]["error"] == "exit_code=1"
    assert "stderr line" in state["failed_stages"]["genome_assembly.step2"]["stderr_tail"]


def test_mark_completed_clears_failed_entry(tmp_path):
    from bioflow.core.checkpoint import load, mark_completed, mark_failed
    wd = tmp_path / "wd"; wd.mkdir()
    mark_failed(wd, "genome_assembly.step2", "old error")
    mark_completed(wd, "genome_assembly.step2", {})
    state = load(wd)
    assert "genome_assembly.step2" not in state.get("failed_stages", {})
    assert "genome_assembly.step2" in state["completed_stages"]


# ── runner fails and records checkpoint ──────────────────────────────────

class _FailOnStepBackend:
    """Mock backend that fails on the first run() call."""
    def __init__(self):
        self.call_count = 0
    def run(self, *, image, command, mounts, cpu, ram_gb, workdir,
            gpu=False, **_ignored):
        from bioflow.core.runner import CommandResult
        self.call_count += 1
        if self.call_count == 1:
            return CommandResult(exit_code=1, stderr="disk full")
        return CommandResult(exit_code=0)


def test_runner_marks_failed_stage_in_checkpoint(tmp_path):
    from bioflow.core.checkpoint import load
    from bioflow.core.runner import run_plan
    plan = _make_plan(tmp_path)

    with pytest.raises(RuntimeError, match="failed"):
        run_plan(plan, backend=_FailOnStepBackend(), show_progress=False)

    state = load(plan.workdir)
    # First stage should be in failed_stages
    first_stage = plan.stages[0].stage_id
    assert first_stage in state.get("failed_stages", {}), \
        "Failed stage must appear in checkpoint.failed_stages"


def test_runner_raises_on_stage_failure(tmp_path):
    from bioflow.core.runner import run_plan
    plan = _make_plan(tmp_path)
    with pytest.raises(RuntimeError):
        run_plan(plan, backend=_FailOnStepBackend(), show_progress=False)


# ── report.py shows failure in HTML ──────────────────────────────────────

def test_report_shows_failed_stage(tmp_path):
    from bioflow.core.checkpoint import mark_failed
    from bioflow.core.report import render_summary
    plan = _make_plan(tmp_path)
    wd = plan.workdir
    Path(wd).mkdir(parents=True, exist_ok=True)

    mark_failed(wd, plan.stages[0].stage_id, "exit_code=137 OOM")

    content = render_summary(plan, tmp_path / "rpt").read_text(encoding="utf-8")
    assert "failed" in content.lower()
    assert "OOM" in content or "exit_code" in content


def test_report_shows_done_and_failed_correctly(tmp_path):
    """First stage done, second stage failed → both reflected in HTML."""
    from bioflow.core.checkpoint import mark_completed, mark_failed
    from bioflow.core.report import render_summary
    plan = _make_plan(tmp_path)
    wd = plan.workdir
    Path(wd).mkdir(parents=True, exist_ok=True)

    mark_completed(wd, plan.stages[0].stage_id, {})
    mark_failed(wd, plan.stages[1].stage_id, "exit_code=1", "some stderr")

    content = render_summary(plan, tmp_path / "rpt").read_text(encoding="utf-8")
    assert "done" in content
    assert "failed" in content.lower()


# ── progress bar (smoke test — just ensure no crash) ─────────────────────

def test_run_plan_with_progress_does_not_crash(tmp_path):
    """show_progress=True with MockBackend must not raise."""
    from bioflow.core.runner import MockBackend, run_plan
    plan = _make_plan(tmp_path)
    run_plan(plan, backend=MockBackend(), show_progress=True)
