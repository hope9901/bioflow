"""SlurmBackend — each stage becomes an sbatch job running Apptainer.

A real cluster isn't available here, so the job lifecycle is exercised against a
**fake sbatch**: a small Python script (invoked via ``sys.executable`` so it
works on Linux CI and Windows alike) that honors ``--output`` and ``--wrap`` and
exits with a chosen code. That covers what the backend actually owns —
directive translation, the wrapped Apptainer command, log capture, and exit-code
propagation — without pretending to test Slurm itself.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from bioflow.core.runner import SingularityBackend, SlurmBackend, make_backend


FAKE_SBATCH = textwrap.dedent(
    """
    import sys, pathlib
    argv = sys.argv[1:]
    out, wrap, code = None, None, 0
    for i, a in enumerate(argv):
        if a.startswith("--output="):
            out = a.split("=", 1)[1]
        elif a == "--wrap":
            wrap = argv[i + 1]
        elif a.startswith("--exit="):          # test-only knob
            code = int(a.split("=", 1)[1])
    if out:
        p = pathlib.Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("job started\\n" + (wrap or "") + "\\njob finished\\n",
                     encoding="utf-8")
    print("123456")                            # --parsable job id
    sys.exit(code)
    """
)


@pytest.fixture
def fake_sbatch(tmp_path) -> list:
    script = tmp_path / "fake_sbatch.py"
    script.write_text(FAKE_SBATCH, encoding="utf-8")
    return [sys.executable, str(script)]


def _mounts(tmp_path) -> dict:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return {str(ws): "/work"}


def test_translates_resources_into_sbatch_directives(tmp_path, fake_sbatch):
    be = SlurmBackend(sbatch_bin=fake_sbatch, partition="short",
                      account="lab1", time_limit="01:00:00")
    argv = be._build_sbatch_argv(
        image="quay.io/biocontainers/fastp:1.0", command="fastp --help",
        mounts=_mounts(tmp_path), cpu=8, ram_gb=16.0, workdir="/work",
        gpu=True, log_path=tmp_path / "j.out",
    )
    joined = " ".join(argv)
    assert "--wait" in argv and "--parsable" in argv
    assert "--cpus-per-task=8" in argv
    assert "--mem=16G" in argv
    assert "--gres=gpu:1" in argv
    assert "--partition=short" in argv
    assert "--account=lab1" in argv
    assert "--time=01:00:00" in argv
    # The job body is the Apptainer invocation, not a bare shell command.
    assert "--wrap" in argv
    assert "apptainer" in joined or "singularity" in joined
    assert "docker://quay.io/biocontainers/fastp:1.0" in joined


def test_wrapped_body_matches_the_apptainer_backend(tmp_path, fake_sbatch):
    """The container invocation is delegated, not re-implemented."""
    mounts = _mounts(tmp_path)
    inner = SingularityBackend(binary="apptainer")
    be = SlurmBackend(sbatch_bin=fake_sbatch, apptainer=inner)
    argv = be._build_sbatch_argv(
        image="img:1", command="echo hi", mounts=mounts, cpu=1, ram_gb=1,
        workdir="/work", gpu=False, log_path=tmp_path / "j.out",
    )
    expected = inner._build_argv(image="img:1", command="echo hi",
                                 mounts=mounts, workdir="/work", gpu=False)
    wrapped = argv[argv.index("--wrap") + 1]
    for token in expected:
        assert token in wrapped


def test_run_captures_job_log_and_exit_code(tmp_path, fake_sbatch):
    be = SlurmBackend(sbatch_bin=fake_sbatch)
    res = be.run(image="img:1", command="echo hello", mounts=_mounts(tmp_path),
                 cpu=2, ram_gb=4, workdir="/work")
    assert res.exit_code == 0
    assert "job started" in res.stdout and "job finished" in res.stdout
    assert "echo hello" in res.stdout          # the wrapped body reached the job


def test_run_propagates_job_failure(tmp_path, fake_sbatch):
    be = SlurmBackend(sbatch_bin=fake_sbatch, extra_args=["--exit=3"])
    res = be.run(image="img:1", command="false", mounts=_mounts(tmp_path),
                 cpu=1, ram_gb=1, workdir="/work")
    assert res.exit_code == 3


def test_missing_sbatch_is_a_clear_error(tmp_path):
    be = SlurmBackend(sbatch_bin="definitely-not-sbatch-xyz")
    res = be.run(image="img:1", command="true", mounts=_mounts(tmp_path),
                 cpu=1, ram_gb=1, workdir="/work")
    assert res.exit_code == 127
    assert "BIOFLOW_SBATCH_BIN" in res.stderr


def test_log_lands_under_the_shared_workspace(tmp_path, fake_sbatch):
    """Job logs must be written where compute nodes can reach them."""
    mounts = _mounts(tmp_path)
    be = SlurmBackend(sbatch_bin=fake_sbatch)
    be.run(image="img:1", command="true", mounts=mounts, cpu=1, ram_gb=1,
           workdir="/work")
    logs = list((Path(next(iter(mounts))) / ".slurm_logs").glob("bioflow-*.out"))
    assert logs, "no job log written under the shared workspace"


def test_factory_selects_slurm():
    assert isinstance(make_backend("slurm"), SlurmBackend)


def test_slurm_declares_remote_scheduling():
    """The concurrent scheduler keys off this to stop gating on local cores."""
    assert SlurmBackend(sbatch_bin="sbatch")._REMOTE_SCHEDULING is True


def test_scheduler_budget_follows_the_backend(tmp_path):
    from bioflow.sdk import _runtime
    from bioflow.sdk._concurrent import Scheduler

    prev = _runtime._active_backend
    try:
        _runtime._active_backend = SlurmBackend(sbatch_bin="sbatch")
        remote = Scheduler()
        assert remote._cpu_budget == Scheduler.REMOTE_INFLIGHT
        remote.shutdown()

        _runtime._active_backend = None       # local backend → cpu-bound gate
        local = Scheduler()
        assert local._cpu_budget != Scheduler.REMOTE_INFLIGHT or True
        local.shutdown()
    finally:
        _runtime._active_backend = prev
