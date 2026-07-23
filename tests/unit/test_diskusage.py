"""Local disk hygiene: see what's eating space, and get it back.

bioflow could check free space and provision multi-GB databases, but offered no
way to see the breakdown or reclaim anything — filling a disk meant deleting
directories by hand. These cover the reporting and the one destructive path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bioflow.core.diskusage import (
    cache_usage,
    db_usage,
    dir_size,
    free_space,
    human,
    remove_db,
)


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_human_reads_like_a_size():
    assert human(512) == "512 B"
    assert human(2048) == "2.0 KB"
    assert human(5 * 1024 ** 3) == "5.0 GB"


def test_dir_size_sums_the_tree(tmp_path):
    _write(tmp_path / "a.bin", 1000)
    _write(tmp_path / "sub" / "b.bin", 2000)
    assert dir_size(tmp_path) == 3000
    assert dir_size(tmp_path / "missing") == 0, "absent path must be 0, not an error"


def test_dir_size_counts_a_file_directly(tmp_path):
    f = tmp_path / "one.bin"
    _write(f, 77)
    assert dir_size(f) == 77


def test_cache_usage_lists_stage_dirs_largest_first(tmp_path):
    ws = tmp_path / "ws"
    _write(ws / ".cache" / "small__aaa" / "f", 100)
    _write(ws / ".cache" / "big__bbb" / "f", 5000)
    (ws / ".cache" / "not_a_dir.txt").write_text("x", encoding="utf-8")

    entries = cache_usage(ws)
    assert [e.name for e in entries] == ["big__bbb", "small__aaa"]
    assert entries[0].bytes == 5000
    assert entries[0].size == "4.9 KB"


def test_cache_usage_on_a_fresh_workspace(tmp_path):
    assert cache_usage(tmp_path / "never-used") == []


def test_db_usage_reports_installed_dbs_only(tmp_path):
    from bioflow.core.db import _DB_CATALOG, _db_top_dir

    # Install one catalogued DB; leave the rest absent.
    key = "eggnog"
    assert key in _DB_CATALOG
    _write(tmp_path / _db_top_dir(key) / "data.bin", 4096)

    entries = db_usage(tmp_path)
    assert [e.name for e in entries] == [key]
    assert entries[0].bytes == 4096
    assert entries[0].detail.startswith("v"), "should show the catalogued version"


def test_remove_db_reclaims_and_reports(tmp_path):
    from bioflow.core.db import _db_top_dir

    key = "eggnog"
    root = tmp_path / _db_top_dir(key)
    _write(root / "data.bin", 2048)
    assert db_usage(tmp_path), "precondition: DB is installed"

    freed = remove_db(key, tmp_path)
    assert freed is not None and freed.bytes == 2048
    assert not root.exists()
    assert db_usage(tmp_path) == [], "should be gone from the report"


def test_remove_db_is_a_noop_when_absent(tmp_path):
    assert remove_db("eggnog", tmp_path) is None


def test_remove_db_rejects_an_unknown_name(tmp_path):
    with pytest.raises(KeyError):
        remove_db("not_a_real_db", tmp_path)


def test_free_space_reads_the_filesystem(tmp_path):
    free, total = free_space(tmp_path)
    assert free > 0 and total >= free
