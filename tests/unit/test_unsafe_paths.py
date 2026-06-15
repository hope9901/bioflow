"""External-input paths with shell-unsafe basenames must fail clearly.

bioflow splices an external file's basename into the container command
unquoted (and can't quote generically — many recipes wrap the whole
command in `bash -c '…'`).  A space / shell metacharacter in the
*basename* would silently corrupt the command, so it must raise an
actionable error.  A spaced *directory* is fine (it maps to /inputs/<n>).
"""
from __future__ import annotations

import pytest

from bioflow.sdk._paths import _collect_external_mounts, _reject_unsafe_basename


class TestRejectUnsafeBasename:

    def test_space_in_name_raises(self, tmp_path):
        f = tmp_path / "my reads.fq.gz"
        f.write_text("x")
        with pytest.raises(ValueError, match="shell-unsafe"):
            _reject_unsafe_basename(f)

    @pytest.mark.parametrize("name", [
        "a;b.fq", "a&b.fq", "a|b.fq", "a$b.fq", "a'b.fq", 'a"b.fq', "a*b.fq",
    ])
    def test_metachars_raise(self, tmp_path, name):
        with pytest.raises(ValueError):
            _reject_unsafe_basename(tmp_path / name)

    def test_clean_name_ok(self, tmp_path):
        # No exception for a normal name.
        _reject_unsafe_basename(tmp_path / "reads_R1.fastq.gz")


class TestCollectExternalMounts:

    def test_spaced_directory_is_allowed(self, tmp_path):
        """Only the basename matters — a spaced parent dir is fine."""
        d = tmp_path / "John Doe data"
        d.mkdir()
        f = d / "reads.fq.gz"      # clean basename
        f.write_text("x")
        ws = tmp_path / "ws"
        ws.mkdir()
        mounts, translation = _collect_external_mounts((f,), {}, ws.resolve())
        # The file's parent (with a space) is mounted at a space-free path.
        assert any(c.startswith("/inputs/") for c in translation.values())
        assert all(" " not in c for c in translation.values())

    def test_spaced_filename_raises(self, tmp_path):
        d = tmp_path / "data"; d.mkdir()
        f = d / "my reads.fq.gz"
        f.write_text("x")
        ws = tmp_path / "ws"; ws.mkdir()
        with pytest.raises(ValueError, match="shell-unsafe"):
            _collect_external_mounts((f,), {}, ws.resolve())

    def test_workspace_internal_paths_unaffected(self, tmp_path):
        """A spaced name *inside* the workspace is handled by the /work
        translator, not the external-mount path, so it is not rejected
        here (and /work is space-free anyway)."""
        ws = tmp_path / "ws"; ws.mkdir()
        inside = ws / "weird name.txt"
        inside.write_text("x")
        # Inside the workspace → no external mount, no rejection.
        mounts, translation = _collect_external_mounts(
            (inside,), {}, ws.resolve()
        )
        assert mounts == {}
        assert translation == {}
