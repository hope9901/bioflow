"""Unit tests for the Apptainer/Singularity backend + the backend factory.

None of these need an actual ``apptainer`` binary or a Docker daemon — the
argv construction and selection logic are pure, and the ``run()`` happy path
is exercised with a fake ``subprocess.Popen``.
"""
from __future__ import annotations

import subprocess

import pytest

from bioflow.core.runner import (
    SingularityBackend,
    make_backend,
)


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------

def test_build_argv_basic():
    b = SingularityBackend(binary="apptainer")
    argv = b._build_argv(
        image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
        command="fastp -i a.fq -o b.fq",
        mounts={"/host/work": "/workspace"},
        workdir="/workspace",
        gpu=False,
    )
    assert argv[:3] == ["apptainer", "exec", "--cleanenv"]
    assert "--bind" in argv and "/host/work:/workspace" in argv
    assert argv[argv.index("--pwd") + 1] == "/workspace"
    # registry ref gets the docker transport, then `sh -c <command>`
    assert "docker://quay.io/biocontainers/fastp:0.23.4--h5f740d0_0" in argv
    assert argv[-3:] == ["sh", "-c", "fastp -i a.fq -o b.fq"]
    assert "--nv" not in argv


def test_build_argv_gpu_adds_nv():
    b = SingularityBackend(binary="singularity")
    argv = b._build_argv(
        image="img:1", command="x", mounts={"/h": "/c"},
        workdir="/workspace", gpu=True,
    )
    assert "--nv" in argv


def test_build_argv_keeps_explicit_transport():
    """A SIF path or oras://… ref must not be double-prefixed with docker://."""
    b = SingularityBackend(binary="apptainer")
    argv = b._build_argv(
        image="oras://example.org/tool:1", command="x", mounts={"/h": "/c"},
        workdir="/workspace", gpu=False,
    )
    assert "oras://example.org/tool:1" in argv
    assert not any(a.startswith("docker://") for a in argv)


def test_build_argv_multiple_binds():
    b = SingularityBackend(binary="apptainer")
    argv = b._build_argv(
        image="img:1", command="x",
        mounts={"/a": "/x", "/b": "/y"},
        workdir="/x", gpu=False,
    )
    assert argv.count("--bind") == 2
    assert "/a:/x" in argv and "/b:/y" in argv


# ---------------------------------------------------------------------------
# factory selection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["singularity", "apptainer", "SINGULARITY"])
def test_make_backend_selects_singularity(name):
    assert isinstance(make_backend(name), SingularityBackend)


def test_make_backend_env(monkeypatch):
    monkeypatch.setenv("BIOFLOW_BACKEND", "apptainer")
    assert isinstance(make_backend(), SingularityBackend)


def test_make_backend_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown BIOFLOW_BACKEND"):
        make_backend("kubernetes")


def test_singularity_advertises_streaming():
    assert getattr(SingularityBackend, "_STREAMING_SUPPORTED", False) is True


# ---------------------------------------------------------------------------
# run() — happy path + missing binary, with a fake Popen
# ---------------------------------------------------------------------------

class _FakePopen:
    def __init__(self, argv, **kw):
        self.argv = argv
        self.stdout = iter(["line one\n", "line two\n"])
        self.returncode = 0

    def wait(self):
        return 0


def test_run_streams_and_returns_zero(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    seen: list[str] = []
    res = SingularityBackend(binary="apptainer").run(
        image="img:1", command="true", mounts={"/h": "/c"},
        cpu=2, ram_gb=4, workdir="/workspace",
        log_callback=seen.append,
    )
    assert res.exit_code == 0
    assert seen == ["line one", "line two"]
    assert "line two" in res.stdout


def test_run_missing_binary_returns_127():
    res = SingularityBackend(binary="definitely-not-real-xyz").run(
        image="img:1", command="true", mounts={"/h": "/c"},
        cpu=1, ram_gb=1, workdir="/workspace",
    )
    assert res.exit_code == 127
    assert "BIOFLOW_APPTAINER_BIN" in res.stderr


def test_run_nonzero_propagates(monkeypatch):
    class _Fail(_FakePopen):
        def __init__(self, argv, **kw):
            super().__init__(argv, **kw)
            self.stdout = iter(["boom\n"])
            self.returncode = 3

    monkeypatch.setattr(subprocess, "Popen", _Fail)
    res = SingularityBackend(binary="apptainer").run(
        image="img:1", command="false", mounts={"/h": "/c"},
        cpu=1, ram_gb=1, workdir="/workspace",
    )
    assert res.exit_code == 3
