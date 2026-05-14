"""BLOCKER-2 regression — input files outside the workspace must be
bind-mounted into the container and their paths rewritten.

Before this fix, a stage command referencing e.g.
``/home/user/reads.fq`` pointed at a path that was neither mounted nor
translated, so every recipe taking external file inputs silently failed.
"""
from __future__ import annotations

import pytest

from bioflow import MockBackend, set_backend, set_workspace, stage
from bioflow.sdk import (
    _apply_external_translation,
    _collect_external_mounts,
)


class _SpyBackend(MockBackend):
    """MockBackend that records the kwargs of the last run() call."""

    def __init__(self):
        super().__init__()
        self.last: dict = {}

    def run(self, **kw):
        self.last = dict(kw)
        return super().run(**kw)


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    set_workspace(ws)
    return ws


class TestCollectExternalMounts:

    def test_external_file_mounts_parent_dir(self, tmp_path, workspace):
        ext = tmp_path / "data" / "reads_R1.fq.gz"
        ext.parent.mkdir()
        ext.write_text("@r1", encoding="utf-8")

        mounts, xlate = _collect_external_mounts((ext,), {}, workspace)
        assert mounts == {str(tmp_path / "data"): "/inputs/0"}
        assert xlate[str(ext)] == "/inputs/0/reads_R1.fq.gz"

    def test_external_directory_mounts_directly(self, tmp_path, workspace):
        ext = tmp_path / "raw_spectra"
        ext.mkdir()

        mounts, xlate = _collect_external_mounts((ext,), {}, workspace)
        assert mounts == {str(ext): "/inputs/0"}
        assert xlate[str(ext)] == "/inputs/0"

    def test_index_prefix_mounts_parent(self, tmp_path, workspace):
        # A Bowtie2 index prefix: the prefix itself does not exist, but
        # its parent dir does (holds hg38.1.bt2, hg38.2.bt2, ...).
        idx_dir = tmp_path / "bowtie2"
        idx_dir.mkdir()
        (idx_dir / "hg38.1.bt2").write_text("x", encoding="utf-8")
        prefix = idx_dir / "hg38"

        mounts, xlate = _collect_external_mounts((prefix,), {}, workspace)
        assert mounts == {str(idx_dir): "/inputs/0"}
        assert xlate[str(prefix)] == "/inputs/0/hg38"

    def test_workspace_paths_are_ignored(self, workspace):
        inside = workspace / "already_here.txt"
        inside.write_text("x", encoding="utf-8")

        mounts, xlate = _collect_external_mounts((inside,), {}, workspace)
        assert mounts == {}
        assert xlate == {}

    def test_stage_result_is_skipped(self, tmp_path, workspace):
        from bioflow.sdk import StageResult
        sr = StageResult(stage="prev", out_dir=workspace / "prev_0001",
                          command="", exit_code=0)
        mounts, xlate = _collect_external_mounts((sr,), {}, workspace)
        assert mounts == {}

    def test_two_inputs_same_dir_mount_once(self, tmp_path, workspace):
        d = tmp_path / "data"
        d.mkdir()
        r1 = d / "R1.fq.gz"
        r2 = d / "R2.fq.gz"
        r1.write_text("x", encoding="utf-8")
        r2.write_text("x", encoding="utf-8")

        mounts, xlate = _collect_external_mounts((r1, r2), {}, workspace)
        assert mounts == {str(d): "/inputs/0"}
        assert xlate[str(r1)] == "/inputs/0/R1.fq.gz"
        assert xlate[str(r2)] == "/inputs/0/R2.fq.gz"

    def test_out_dir_kwarg_is_skipped(self, tmp_path, workspace):
        ext = tmp_path / "ext.txt"
        ext.write_text("x", encoding="utf-8")
        # out_dir is SDK-injected and lives in the workspace — never mount it
        mounts, _ = _collect_external_mounts(
            (), {"out_dir": workspace / "s_0001", "infile": ext}, workspace,
        )
        assert mounts == {str(tmp_path): "/inputs/0"}


class TestApplyExternalTranslation:

    def test_longest_path_replaced_first(self):
        xlate = {
            "/a/b": "/inputs/0",
            "/a/b/file.txt": "/inputs/0/file.txt",
        }
        cmd = "cat /a/b/file.txt > /tmp/out"
        out = _apply_external_translation(cmd, xlate)
        assert "/inputs/0/file.txt" in out
        # the file path must not be mangled into /inputs/0/file.txt-style
        # by the parent-dir entry being applied first
        assert "/inputs/0/inputs" not in out


class TestEndToEndExternalInput:

    def test_external_file_is_mounted_and_translated(self, tmp_path):
        ext_dir = tmp_path / "external"
        ext_dir.mkdir()
        ext_file = ext_dir / "reads.fastq.gz"
        ext_file.write_text("@read", encoding="utf-8")

        ws = tmp_path / "ws"
        ws.mkdir()
        set_workspace(ws)
        spy = _SpyBackend()
        set_backend(spy)

        @stage(image="busybox:latest", cpu=1, ram_gb=1, cache=False)
        def consume(infile, *, out_dir):
            return f"cat {infile} > {out_dir}/copy.txt"

        result = consume(ext_file)
        assert result.ok
        # the external dir is mounted
        assert spy.last["mounts"][str(ext_dir)] == "/inputs/0"
        # the workspace is still mounted
        assert str(ws) in spy.last["mounts"]
        # the command references the container path, not the host path
        assert "/inputs/0/reads.fastq.gz" in spy.last["command"]
        assert str(ext_file) not in spy.last["command"]
