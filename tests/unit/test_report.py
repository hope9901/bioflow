"""Unit tests for bioflow.core.report (Step 9)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


def _make_plan(tmp_path: Path):
    """Build a minimal prokaryote_denovo_short ExecutionPlan for testing."""
    from bioflow.core.planner import plan_from_preset

    cfg = {
        "pipeline": "genome_assembly",
        "species": "prokaryote",
        "read_type": "short",
        "mode": "de_novo",
        "inputs": {
            "sample_id": "ecoli",
            "r1": "/in/R1.fastq.gz",
            "r2": "/in/R2.fastq.gz",
        },
        "workdir": str(tmp_path / "wd"),
        "registry_dir": str(REGISTRY_DIR),
    }
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")
    return plan_from_preset("prokaryote_denovo_short", cfg_path)


# ---------------------------------------------------------------------------
# render_summary tests (no Docker needed)
# ---------------------------------------------------------------------------

def test_render_summary_creates_html(tmp_path):
    plan = _make_plan(tmp_path)
    from bioflow.core.report import render_summary
    out = render_summary(plan, tmp_path / "reports")

    assert out.exists()
    assert out.suffix == ".html"
    content = out.read_text(encoding="utf-8")
    assert "bioflow" in content
    assert "genome_assembly" in content
    assert "prokaryote" in content


def test_render_summary_contains_all_stages(tmp_path):
    plan = _make_plan(tmp_path)
    from bioflow.core.report import render_summary
    out = render_summary(plan, tmp_path / "reports")
    content = out.read_text(encoding="utf-8")

    for stage in plan.stages:
        assert stage.tool_id in content, f"tool_id {stage.tool_id!r} missing from summary"
        assert stage.stage_id in content, f"stage_id {stage.stage_id!r} missing from summary"


def test_render_summary_shows_done_for_completed_stages(tmp_path):
    plan = _make_plan(tmp_path)
    workdir = plan.workdir
    workdir.mkdir(parents=True, exist_ok=True)

    # Mark first stage as completed in checkpoint
    state = {"completed_stages": [plan.stages[0].stage_id]}
    (workdir / ".bioflow_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    from bioflow.core.report import render_summary
    content = render_summary(plan, tmp_path / "reports").read_text(encoding="utf-8")

    # First stage should have class "ok" / "done" text
    assert "done" in content


def test_render_summary_includes_multiqc_link(tmp_path):
    plan = _make_plan(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    fake_multiqc = reports_dir / "multiqc_report.html"
    fake_multiqc.write_text("<html>multiqc</html>", encoding="utf-8")

    from bioflow.core.report import render_summary
    content = render_summary(
        plan, reports_dir, multiqc_report=fake_multiqc
    ).read_text(encoding="utf-8")

    assert "multiqc_report.html" in content
    assert "MultiQC" in content


def test_render_summary_no_multiqc_link_when_file_missing(tmp_path):
    plan = _make_plan(tmp_path)
    from bioflow.core.report import render_summary
    content = render_summary(
        plan, tmp_path / "reports", multiqc_report=tmp_path / "nonexistent.html"
    ).read_text(encoding="utf-8")

    assert "multiqc_report.html" not in content


# ---------------------------------------------------------------------------
# generate_reports convenience wrapper
# ---------------------------------------------------------------------------

def test_generate_reports_skip_multiqc(tmp_path):
    """skip_multiqc=True → multiqc=None, summary is still produced."""
    plan = _make_plan(tmp_path)
    from bioflow.core.report import generate_reports
    result = generate_reports(plan, tmp_path / "reports", skip_multiqc=True)

    assert result["multiqc"] is None
    assert result["summary"] is not None
    assert result["summary"].exists()


def test_generate_reports_multiqc_graceful_on_no_docker(tmp_path):
    """When Docker is unavailable, MultiQC is skipped and summary still renders."""
    plan = _make_plan(tmp_path)

    # Patch DockerBackend to raise immediately
    with patch(
        "bioflow.core.report.run_multiqc",
        return_value=None,
    ):
        from bioflow.core.report import generate_reports
        result = generate_reports(plan, tmp_path / "reports")

    assert result["multiqc"] is None
    assert result["summary"].exists()


# ---------------------------------------------------------------------------
# run_multiqc — mock backend
# ---------------------------------------------------------------------------

def test_run_multiqc_calls_backend_and_returns_path(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    out_dir = tmp_path / "out"

    # Fake MultiQC that writes the expected output file
    def fake_run(*, image, command, mounts, cpu, ram_gb, workdir):
        (out_dir / "multiqc_report.html").write_text("<html/>", encoding="utf-8")

    mock_backend = MagicMock()
    mock_backend.run.side_effect = fake_run

    from bioflow.core.report import run_multiqc
    result = run_multiqc(workdir, out_dir, backend=mock_backend)

    assert result is not None
    assert result.name == "multiqc_report.html"
    mock_backend.run.assert_called_once()


def test_run_multiqc_returns_none_on_backend_failure(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    out_dir = tmp_path / "out"

    mock_backend = MagicMock()
    mock_backend.run.side_effect = RuntimeError("container crashed")

    from bioflow.core.report import run_multiqc
    result = run_multiqc(workdir, out_dir, backend=mock_backend)

    assert result is None
