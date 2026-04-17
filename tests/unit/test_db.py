"""Unit tests for bioflow.core.db (item 1 — db fetch)."""
from __future__ import annotations

import io
import gzip
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# list_dbs
# ---------------------------------------------------------------------------

def test_list_dbs_returns_entries():
    from bioflow.core.db import list_dbs, _DB_CATALOG
    rows = list_dbs()
    assert len(rows) == len(_DB_CATALOG)
    for r in rows:
        assert "key" in r and "size_gb" in r and "used_by" in r


def test_list_dbs_all_have_used_by():
    from bioflow.core.db import list_dbs
    for r in list_dbs():
        assert isinstance(r["used_by"], list)
        assert len(r["used_by"]) > 0


# ---------------------------------------------------------------------------
# fetch_db
# ---------------------------------------------------------------------------

def _make_fake_response(content: bytes) -> MagicMock:
    """Build a mock that behaves like urllib.request.urlopen response."""
    resp = MagicMock()
    resp.headers = {"Content-Length": str(len(content))}
    resp.read.side_effect = [content, b""]   # first call returns data, second EOF
    return resp


def test_fetch_db_unknown_name_raises(tmp_path):
    from bioflow.core.db import fetch_db
    with pytest.raises(KeyError, match="Unknown database"):
        fetch_db("does_not_exist", tmp_path)


def test_fetch_db_skip_if_exists(tmp_path):
    """When destination file already exists, download must be skipped."""
    from bioflow.core.db import fetch_db, _DB_CATALOG
    key = "busco_bacteria"
    dest_file = tmp_path / _DB_CATALOG[key]["dest_file"]
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    dest_file.write_bytes(b"existing")

    called = []

    def _opener(url):
        called.append(url)
        return _make_fake_response(b"new data")

    result = fetch_db(key, tmp_path, skip_if_exists=True, _opener=_opener)
    assert len(called) == 0, "Opener must not be called when file already exists"
    assert result == dest_file


def test_fetch_db_downloads_when_missing(tmp_path):
    """fetch_db creates the destination file from the mock response."""
    from bioflow.core.db import fetch_db, _DB_CATALOG
    key = "busco_bacteria"
    payload = b"mock database content"
    dest_file = tmp_path / _DB_CATALOG[key]["dest_file"]

    # Mock the response: read returns payload once, then EOF
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": str(len(payload))}
    # Use side_effect list for sequential calls
    chunks = [payload[i:i+65536] for i in range(0, len(payload), 65536)] + [b""]
    mock_resp.read.side_effect = chunks

    result = fetch_db(key, tmp_path, _opener=lambda url: mock_resp)
    assert result.exists()
    assert result.read_bytes() == payload


def test_fetch_db_removes_partial_on_error(tmp_path):
    """If the download fails mid-way, no partial file should remain."""
    from bioflow.core.db import fetch_db

    def _bad_opener(url):
        raise OSError("network error")

    with pytest.raises(RuntimeError, match="Failed to download"):
        fetch_db("busco_bacteria", tmp_path, _opener=_bad_opener)

    from bioflow.core.db import _DB_CATALOG
    dest = tmp_path / _DB_CATALOG["busco_bacteria"]["dest_file"]
    assert not dest.exists(), "Partial file must be cleaned up on error"


# ---------------------------------------------------------------------------
# verify_db
# ---------------------------------------------------------------------------

def test_verify_db_unknown_name_raises(tmp_path):
    from bioflow.core.db import verify_db
    with pytest.raises(KeyError):
        verify_db("nope", tmp_path)


def test_verify_db_returns_false_when_missing(tmp_path):
    from bioflow.core.db import verify_db
    assert verify_db("busco_bacteria", tmp_path) is False


def test_verify_db_returns_true_when_present_no_md5(tmp_path):
    """When catalog has no MD5, presence check is sufficient."""
    from bioflow.core.db import verify_db, _DB_CATALOG
    key = "busco_bacteria"
    dest = tmp_path / _DB_CATALOG[key]["dest_file"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"data")
    # catalog has md5=None → should pass without checksum
    assert verify_db(key, tmp_path) is True
