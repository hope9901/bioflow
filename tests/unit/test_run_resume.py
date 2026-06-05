"""End-to-end resume semantics for `bioflow run`.

Scenario covered
----------------
1. First run of a 3-stage preset; stage 2 raises mid-execution
2. ``.bioflow_state.json`` records stage 1 as completed, stage 2 as failed
3. Second run (default behaviour) skips stage 1 and re-attempts stage 2
4. ``--fresh`` deletes the state file and re-runs every stage
5. ``bioflow status`` summarises the checkpoint and exits 0 even without a
   state file.

The fault injection uses a hand-rolled backend that fails on a chosen
``stage_id``; this lets us run the real ``run_plan`` without Docker.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bioflow.core.checkpoint import STATE_FILE, load
from bioflow.core.planner import ExecutionPlan, StagePlan
from bioflow.core.registry import Tool
from bioflow.core.runner import CommandResult, run_plan


# ---------------------------------------------------------------------------
# Fault-injecting backend
# ---------------------------------------------------------------------------

class FaultyBackend:
    """MockBackend variant that raises a CommandResult error on one stage_id."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[dict] = []

    def run(
        self, *, image, command, mounts, cpu, ram_gb, workdir,
    ) -> CommandResult:
        # Map back from the workdir to the stage_id we're running.  The
        # runner sets workdir="/workspace" inside the container, so we
        # inspect the rendered command which includes the per-stage
        # out_dir.  For the test we tag a probe string into each command.
        stage_id = None
        for marker in ("stage_a", "stage_b", "stage_c"):
            if marker in command:
                stage_id = marker
                break
        self.calls.append({
            "image": image,
            "command": command,
            "stage_id": stage_id,
        })
        if stage_id and stage_id == self.fail_on:
            return CommandResult(
                exit_code=2,
                stderr=f"simulated failure for {stage_id}",
            )
        return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# Plan fixture: 3 stages, tagged so FaultyBackend can recognise them
# ---------------------------------------------------------------------------

def _build_plan(tmp_path: Path) -> tuple[ExecutionPlan, list[Tool]]:
    """Three-stage plan whose command_templates embed 'stage_a/b/c'."""
    tools: list[Tool] = []
    for tag in ("stage_a", "stage_b", "stage_c"):
        tools.append(Tool.model_validate({
            "id": tag,
            "name": tag,
            "version": "1",
            "category": "qc",
            "stage": [tag],
            "applicable": {"species": ["any"], "read_type": ["short"], "mode": ["any"]},
            "container": {"image": f"fake/{tag}:1"},
            "resources": {
                "min": {"cpu": 1, "ram_gb": 1},
                "recommended": {"cpu": 1, "ram_gb": 1},
            },
            "command_template": f"echo {tag} -> {{out_dir}}",
        }))

    plan = ExecutionPlan(
        pipeline="genome_assembly",
        species="any",
        read_type="short",
        mode="any",
        workdir=str(tmp_path),
        inputs={},
        stages=[
            StagePlan(stage_id="stage_a", tool_id="stage_a"),
            StagePlan(stage_id="stage_b", tool_id="stage_b"),
            StagePlan(stage_id="stage_c", tool_id="stage_c"),
        ],
    )
    return plan, tools


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResumeFromFailure:

    def test_failure_records_state(self, tmp_path, monkeypatch):
        plan, tools = _build_plan(tmp_path)
        monkeypatch.setattr(
            "bioflow.core.runner.load_registry", lambda _d: tools
        )

        backend = FaultyBackend(fail_on="stage_b")
        with pytest.raises(RuntimeError) as exc:
            run_plan(plan, backend=backend, show_progress=False)
        assert "stage_b" in str(exc.value)

        state = load(tmp_path)
        assert state["completed_stages"] == ["stage_a"]
        assert "stage_b" in state.get("failed_stages", {})
        assert "stage_c" not in state["completed_stages"]
        # stage_a + stage_b were attempted, stage_c was never tried
        attempted = [c["stage_id"] for c in backend.calls]
        assert attempted == ["stage_a", "stage_b"]

    def test_resume_skips_completed_and_runs_remaining(self, tmp_path, monkeypatch):
        plan, tools = _build_plan(tmp_path)
        monkeypatch.setattr(
            "bioflow.core.runner.load_registry", lambda _d: tools
        )

        # First run — fails on stage_b
        run_plan(plan, backend=FaultyBackend(fail_on="stage_b"),
                 show_progress=False) if False else None  # placate ruff
        try:
            run_plan(plan, backend=FaultyBackend(fail_on="stage_b"),
                     show_progress=False)
        except RuntimeError:
            pass

        # Second run — no fault this time, no fresh wipe
        backend2 = FaultyBackend(fail_on=None)
        run_plan(plan, backend=backend2, show_progress=False)

        # stage_a should NOT have been re-executed
        attempted_2 = [c["stage_id"] for c in backend2.calls]
        assert "stage_a" not in attempted_2, (
            f"stage_a should have been skipped on resume, got {attempted_2}"
        )
        assert attempted_2 == ["stage_b", "stage_c"]

        # State now shows everything completed
        state = load(tmp_path)
        assert set(state["completed_stages"]) == {"stage_a", "stage_b", "stage_c"}

    def test_fresh_wipe_reruns_everything(self, tmp_path, monkeypatch):
        plan, tools = _build_plan(tmp_path)
        monkeypatch.setattr(
            "bioflow.core.runner.load_registry", lambda _d: tools
        )

        # Seed state as if a previous run had finished stage_a + stage_b.
        from bioflow.core.checkpoint import mark_completed
        mark_completed(tmp_path, "stage_a", {"stage_dir": str(tmp_path / "stage_a")})
        mark_completed(tmp_path, "stage_b", {"stage_dir": str(tmp_path / "stage_b")})

        # Simulate `--fresh` by wiping the state file before run_plan.
        (tmp_path / STATE_FILE).unlink()

        backend = FaultyBackend(fail_on=None)
        run_plan(plan, backend=backend, show_progress=False)

        attempted = [c["stage_id"] for c in backend.calls]
        assert attempted == ["stage_a", "stage_b", "stage_c"], (
            f"--fresh should re-run all three stages, got {attempted}"
        )


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def _invoke(argv):
    from typer.testing import CliRunner

    from bioflow.cli import app

    return CliRunner().invoke(app, argv)


class TestStatusCli:

    def test_status_on_empty_workspace(self, tmp_path):
        result = _invoke(["status", str(tmp_path)])
        assert result.exit_code == 0
        assert "no checkpoint" in result.stdout

    def test_status_after_partial_run(self, tmp_path):
        from bioflow.core.checkpoint import mark_completed, mark_failed
        mark_completed(tmp_path, "stage_a", {"stage_dir": str(tmp_path / "a")})
        mark_failed(tmp_path, "stage_b", "exit_code=2", "simulated failure")

        result = _invoke(["status", str(tmp_path)])
        assert result.exit_code == 0
        assert "stage_a" in result.stdout
        assert "stage_b" in result.stdout
        assert "completed_stages" in result.stdout
        assert "failed_stages" in result.stdout

    def test_status_json(self, tmp_path):
        import json
        from bioflow.core.checkpoint import mark_completed
        mark_completed(tmp_path, "stage_a", {"stage_dir": str(tmp_path / "a")})

        result = _invoke(["status", str(tmp_path), "--json"])
        assert result.exit_code == 0
        doc = json.loads(result.stdout)
        assert "stage_a" in doc["completed_stages"]


class TestRunCliFlags:

    def test_fresh_and_resume_are_mutually_exclusive(self, tmp_path):
        # Write a no-op config so the file exists; run will reject both flags.
        cfg = tmp_path / "noop.yaml"
        cfg.write_text("pipeline: x\n", encoding="utf-8")
        result = _invoke(["run", str(cfg), "--fresh", "--resume"])
        assert result.exit_code == 2
        assert "mutually exclusive" in result.stdout
