"""Runner end-to-end test with MockBackend (no Docker required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bioflow.core.checkpoint import STATE_FILE
from bioflow.core.planner import ExecutionPlan, StagePlan
from bioflow.core.runner import MockBackend, run_plan


REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


def _plan(workdir: Path) -> ExecutionPlan:
    return ExecutionPlan(
        pipeline="genome_assembly",
        species="prokaryote",
        read_type="short",
        mode="de_novo",
        inputs={
            "r1": "/workspace/in/sample_R1.fastq.gz",
            "r2": "/workspace/in/sample_R2.fastq.gz",
            "assembly_fasta": "/workspace/out/assembly.fasta",
            "inputs": "/workspace/in/sample_R1.fastq.gz",
            "sample_id": "sample",
        },
        stages=[
            StagePlan(stage_id="genome_assembly.step1", tool_id="fastp"),
            StagePlan(stage_id="genome_assembly.step2", tool_id="spades"),
            StagePlan(stage_id="genome_assembly.step3", tool_id="quast"),
        ],
        workdir=workdir,
        registry_dir=REGISTRY_DIR,
    )


def test_runner_executes_all_stages_in_order(tmp_path):
    backend = MockBackend()
    run_plan(_plan(tmp_path), backend=backend, registry_dir=REGISTRY_DIR)

    assert len(backend.calls) == 3
    images = [c["image"] for c in backend.calls]
    assert "fastp" in images[0]
    assert "spades" in images[1]
    assert "quast" in images[2]

    # Every call got the shared /workspace mount
    for call in backend.calls:
        assert call["workdir"] == "/workspace"
        assert "/workspace" in call["mounts"].values()

    # Commands had their templates rendered (fastp.yaml uses {r1}/{r2}/{cpu}/{out_dir})
    fastp_cmd = backend.calls[0]["command"]
    assert "/workspace/in/sample_R1.fastq.gz" in fastp_cmd
    assert "--thread" in fastp_cmd


def test_runner_writes_checkpoint_and_skips_on_resume(tmp_path):
    backend = MockBackend()
    run_plan(_plan(tmp_path), backend=backend, registry_dir=REGISTRY_DIR)
    assert len(backend.calls) == 3

    state_file = tmp_path / STATE_FILE
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(state["completed_stages"]) == 3

    # Resume: all stages already checkpointed → no new calls
    backend2 = MockBackend()
    run_plan(_plan(tmp_path), backend=backend2, registry_dir=REGISTRY_DIR)
    assert backend2.calls == []


def test_runner_rejects_unknown_tool(tmp_path):
    plan = _plan(tmp_path)
    plan.stages = [StagePlan(stage_id="genome_assembly.step1", tool_id="does_not_exist")]
    with pytest.raises(ValueError, match="not found in registry"):
        run_plan(plan, backend=MockBackend(), registry_dir=REGISTRY_DIR)
