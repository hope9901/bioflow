"""Integration tests for DockerBackend (requires a running Docker daemon).

All tests in this file are marked ``@pytest.mark.docker`` and are **skipped
automatically** when Docker is not reachable.  Run explicitly with:

    pytest tests/integration/ -m docker -v

These tests use ``alpine:3.19`` to avoid pulling large images.

What is verified:
  1. A simple echo command exits 0 and the stdout is captured.
  2. A failing command (exit 1) returns exit_code=1 without raising.
  3. A volume mount lets the container write a file to the host.
  4. Log streaming (log_callback) receives each line of output.
  5. ``run_plan`` end-to-end with DockerBackend on a 1-stage plan using
     alpine:3.19 — exercises the full sibling-container path.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    try:
        import docker  # type: ignore[import-not-found]
        docker.from_env().ping()
        return True
    except Exception:
        return False


docker_required = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not reachable — skipping integration tests",
)

ALPINE = "alpine:3.19"


@pytest.fixture(scope="module")
def docker_backend():
    from bioflow.core.runner import DockerBackend
    return DockerBackend()


# ---------------------------------------------------------------------------
# Test 1: simple echo → exit 0 + stdout
# ---------------------------------------------------------------------------

@docker_required
def test_docker_backend_echo(docker_backend, tmp_path):
    result = docker_backend.run(
        image=ALPINE,
        command="echo hello-bioflow",
        mounts={str(tmp_path): "/workspace"},
        cpu=1,
        ram_gb=0.25,
        workdir="/workspace",
    )
    assert result.exit_code == 0
    assert "hello-bioflow" in result.stdout


# ---------------------------------------------------------------------------
# Test 2: failing command → exit_code != 0, does NOT raise
# ---------------------------------------------------------------------------

@docker_required
def test_docker_backend_failure_exit_code(docker_backend, tmp_path):
    result = docker_backend.run(
        image=ALPINE,
        command="exit 42",
        mounts={str(tmp_path): "/workspace"},
        cpu=1,
        ram_gb=0.25,
        workdir="/workspace",
    )
    assert result.exit_code == 42


# ---------------------------------------------------------------------------
# Test 3: volume mount — container writes file visible on host
# ---------------------------------------------------------------------------

@docker_required
def test_docker_backend_volume_write(docker_backend, tmp_path):
    result = docker_backend.run(
        image=ALPINE,
        command="echo bioflow-test > /workspace/sentinel.txt",
        mounts={str(tmp_path): "/workspace"},
        cpu=1,
        ram_gb=0.25,
        workdir="/workspace",
    )
    assert result.exit_code == 0
    sentinel = tmp_path / "sentinel.txt"
    assert sentinel.exists(), "Container must have written sentinel.txt to the volume"
    assert "bioflow-test" in sentinel.read_text()


# ---------------------------------------------------------------------------
# Test 4: log_callback receives streamed output lines
# ---------------------------------------------------------------------------

@docker_required
def test_docker_backend_log_streaming(docker_backend, tmp_path):
    received: list[str] = []

    def _cb(line: str) -> None:
        received.append(line)

    result = docker_backend.run(
        image=ALPINE,
        command="for i in 1 2 3; do echo line$i; done",
        mounts={str(tmp_path): "/workspace"},
        cpu=1,
        ram_gb=0.25,
        workdir="/workspace",
        log_callback=_cb,
    )
    assert result.exit_code == 0
    # log_callback must have been called at least 3 times
    joined = "\n".join(received)
    assert "line1" in joined
    assert "line2" in joined
    assert "line3" in joined


# ---------------------------------------------------------------------------
# Test 5: run_plan with DockerBackend — 1-stage alpine plan
# ---------------------------------------------------------------------------

@docker_required
def test_run_plan_with_docker_backend_single_stage(tmp_path):
    """Full pipeline run with real Docker: 1 stage that echoes and exits 0."""
    import yaml  # noqa: PLC0415
    from bioflow.core.planner import ExecutionPlan, StagePlan  # noqa: PLC0415
    from bioflow.core.registry import load_registry  # noqa: PLC0415
    from bioflow.core.runner import DockerBackend, run_plan  # noqa: PLC0415

    registry_dir = Path(__file__).resolve().parents[2] / "registry"

    # Patch fastp tool's image to alpine and command to echo, to avoid pulling fastp
    tools = load_registry(registry_dir)
    fastp = next(t for t in tools if t.id == "fastp")

    # We monkey-patch the fastp tool's image + command template in a temp registry
    import copy  # noqa: PLC0415
    fastp_patched = copy.deepcopy(fastp)
    fastp_patched.container.image = ALPINE
    fastp_patched.command_template = "echo fastp-mock-ok"

    # Build a minimal 1-stage plan
    workdir = tmp_path / "wd"
    plan = ExecutionPlan(
        pipeline="genome_assembly",
        species="prokaryote", read_type="short", mode="de_novo",
        inputs={"sample_id": "test", "r1": "/r1.fq", "r2": "/r2.fq"},
        stages=[StagePlan(
            stage_id="genome_assembly.step1",
            tool_id="fastp",
            params={},
        )],
        workdir=workdir,
        registry_dir=registry_dir,
    )

    # Monkey-patch load_registry to return our patched tool
    original_load = __import__(
        "bioflow.core.registry", fromlist=["load_registry"]
    ).load_registry

    def _patched_load(d):
        ts = original_load(d)
        return [fastp_patched if t.id == "fastp" else t for t in ts]

    import bioflow.core.runner as runner_mod  # noqa: PLC0415
    runner_mod.load_registry = _patched_load

    try:
        run_plan(plan, backend=DockerBackend(), show_progress=False)
    finally:
        runner_mod.load_registry = original_load

    from bioflow.core.checkpoint import load as load_state  # noqa: PLC0415
    state = load_state(workdir)
    assert "genome_assembly.step1" in state["completed_stages"]
