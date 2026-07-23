"""Staging end-to-end with real containers.

The unit tests use a recording inner backend; this runs the same flow through
Docker so the claim "a worker that cannot see the workspace still produces
correct results" is checked against an actual container — including that the
workspace is never in its mount table.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bioflow import pipeline, set_backend, set_workspace, stage
from bioflow.core.runner import DockerBackend
from bioflow.core.staging import LocalDirStore, StagingBackend

try:
    _docker_unavailable = None
    DockerBackend()
except Exception as exc:  # pragma: no cover - depends on host
    _docker_unavailable = str(exc)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.slow,
    pytest.mark.skipif(
        _docker_unavailable is not None,
        reason=f"Docker not reachable: {_docker_unavailable}",
    ),
]

IMG = "quay.io/biocontainers/bcftools:1.23.1--hb2cee57_0"


@stage(image=IMG, cpu=1, ram_gb=1)
def produce(text, *, out_dir):
    return f"sh -c 'echo {text} > {out_dir}/produced.txt'"


@stage(image=IMG, cpu=1, ram_gb=1, depends_on=produce)
def consume(up, *, out_dir):
    # Reads the upstream out_dir — only works if staging shipped it in.
    return f"sh -c 'cat {up.out_dir}/produced.txt > {out_dir}/consumed.txt'"


@pipeline(stages=[produce, consume])
def chain(text):
    return consume(produce(text))


class SpyDocker(DockerBackend):
    """Docker, but records every mount table it was handed."""

    def __init__(self) -> None:
        super().__init__()
        self.mount_tables: list[dict] = []

    def run(self, **kw):
        self.mount_tables.append(dict(kw.get("mounts") or {}))
        return super().run(**kw)


def test_staged_pipeline_matches_a_normal_run(tmp_path):
    """Same pipeline, once normally and once fully staged: identical output,
    and the staged run never mounts the workspace."""
    # 1. plain Docker run
    plain_ws = tmp_path / "plain"
    set_workspace(plain_ws)
    set_backend(DockerBackend())
    plain = chain("hello-staging")
    assert plain.ok, "baseline (unstaged) run failed"
    plain_text = (plain.out_dir / "consumed.txt").read_text().strip()

    # 2. staged run — the container gets a sandbox, never the workspace
    staged_ws = tmp_path / "staged"
    set_workspace(staged_ws)
    spy = SpyDocker()
    store = LocalDirStore(tmp_path / "store")
    set_backend(StagingBackend(spy, store))
    try:
        staged = chain("hello-staging")
        assert staged.ok, (staged.stderr or staged.stdout)[:400]
        staged_text = (staged.out_dir / "consumed.txt").read_text().strip()
    finally:
        set_backend(None)

    # Same result through a worker that never saw the workspace.
    assert staged_text == plain_text == "hello-staging"

    # The workspace must not appear in any container's mounts.
    for table in spy.mount_tables:
        for host in table:
            assert Path(host) != staged_ws, "worker was given the workspace"
        assert any("bioflow-stage-" in h for h in table), \
            "expected the sandbox to be mounted instead"

    # Both stages published under their content-addressed keys, so another
    # machine could reuse them.
    published = list((tmp_path / "store" / ".cache").glob("*"))
    assert len(published) >= 2, f"expected staged results, got {published}"


def test_second_machine_reuses_published_inputs(tmp_path):
    """The point of a content-addressed store: a fresh workspace with only the
    store can still run the downstream stage."""
    ws = tmp_path / "ws"
    set_workspace(ws)
    store = LocalDirStore(tmp_path / "store")
    set_backend(StagingBackend(DockerBackend(), store))
    try:
        first = chain("reuse-me")
        assert first.ok

        # Simulate a different machine: wipe the upstream from the workspace,
        # leaving only what the store holds.
        for d in (ws / ".cache").glob("produce__*"):
            shutil.rmtree(d, ignore_errors=True)
        for d in (ws / ".cache").glob("consume__*"):
            shutil.rmtree(d, ignore_errors=True)

        again = chain("reuse-me")
        assert again.ok, (again.stderr or again.stdout)[:400]
        assert (again.out_dir / "consumed.txt").read_text().strip() == "reuse-me"
    finally:
        set_backend(None)
