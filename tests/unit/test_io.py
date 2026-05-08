"""Phase 2F — bioflow.io operational quirk absorption tests."""
from __future__ import annotations

import os
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bioflow.io import (
    write_text,
    read_text,
    write_bytes,
    read_bytes,
    atomic_replace,
    download_url,
    DownloadError,
    retry,
    batched_urls,
)


# ---------------------------------------------------------------------------
# Text IO — CRLF / encoding traps
# ---------------------------------------------------------------------------

class TestTextIO:

    def test_write_normalises_crlf_to_lf(self, tmp_path):
        target = tmp_path / "out.txt"
        write_text(target, "a\r\nb\r\nc\n")
        raw = target.read_bytes()
        assert b"\r" not in raw
        assert raw == b"a\nb\nc\n"

    def test_write_normalises_lone_cr_to_lf(self, tmp_path):
        target = tmp_path / "out.txt"
        write_text(target, "a\rb\rc")
        assert target.read_bytes() == b"a\nb\nc"

    def test_write_atomic_no_partial_on_error(self, tmp_path, monkeypatch):
        target = tmp_path / "out.txt"
        target.write_text("original")

        # Force os.replace to raise — we should NOT see a half-written file
        original_replace = os.replace

        def boom(src, dst):
            raise OSError("simulated rename failure")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            write_text(target, "new content that should not land")

        # Original is intact, no .tmp leftovers
        assert target.read_text() == "original"
        leftover_tmps = list(tmp_path.glob(".out.txt.*.tmp"))
        assert not leftover_tmps

    def test_write_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "f.txt"
        write_text(target, "hi")
        assert target.read_text() == "hi"

    def test_read_text_replaces_bad_bytes(self, tmp_path):
        target = tmp_path / "weird.txt"
        # Write bytes that aren't valid UTF-8
        target.write_bytes(b"hello\xff\xfeworld")
        # Default errors="replace" means we get � substitution chars
        text = read_text(target)
        assert "hello" in text
        assert "world" in text
        assert "�" in text

    def test_read_text_strict_can_still_raise(self, tmp_path):
        target = tmp_path / "weird.txt"
        target.write_bytes(b"hello\xff\xfeworld")
        with pytest.raises(UnicodeDecodeError):
            read_text(target, errors="strict")


class TestBytesIO:

    def test_write_bytes_atomic(self, tmp_path):
        target = tmp_path / "blob.bin"
        write_bytes(target, b"\x00\x01\x02")
        assert read_bytes(target) == b"\x00\x01\x02"

    def test_write_bytes_overwrites(self, tmp_path):
        target = tmp_path / "blob.bin"
        write_bytes(target, b"first")
        write_bytes(target, b"second")
        assert read_bytes(target) == b"second"


class TestAtomicReplace:

    def test_replace_within_same_dir(self, tmp_path):
        src = tmp_path / "a.txt"; src.write_text("hi")
        dst = tmp_path / "b.txt"
        atomic_replace(src, dst)
        assert dst.read_text() == "hi"
        assert not src.exists()

    def test_replace_creates_parent_dir(self, tmp_path):
        src = tmp_path / "a.txt"; src.write_text("hi")
        dst = tmp_path / "subdir" / "b.txt"
        atomic_replace(src, dst)
        assert dst.read_text() == "hi"


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

class TestRetry:

    def test_succeeds_on_first_try(self):
        calls = [0]
        @retry(attempts=3, initial_delay=0)
        def f():
            calls[0] += 1
            return "ok"
        assert f() == "ok"
        assert calls[0] == 1

    def test_retries_until_success(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        calls = [0]
        @retry(attempts=5, initial_delay=0.01)
        def f():
            calls[0] += 1
            if calls[0] < 3:
                raise ValueError("flake")
            return "got it"
        assert f() == "got it"
        assert calls[0] == 3

    def test_raises_after_exhausting_attempts(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        @retry(attempts=2, initial_delay=0.01)
        def f():
            raise ValueError("always fails")
        with pytest.raises(ValueError, match="always fails"):
            f()

    def test_only_retries_specified_exceptions(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        calls = [0]
        @retry(attempts=5, initial_delay=0.01, exceptions=(ValueError,))
        def f():
            calls[0] += 1
            raise KeyError("not retryable")
        with pytest.raises(KeyError):
            f()
        # No retry happened
        assert calls[0] == 1

    def test_on_retry_callback_invoked(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        seen = []
        @retry(attempts=3, initial_delay=0.01,
               on_retry=lambda i, exc: seen.append((i, str(exc))))
        def f():
            raise RuntimeError("bang")
        with pytest.raises(RuntimeError):
            f()
        # Two callbacks: between attempts 1→2 and 2→3
        assert len(seen) == 2

    def test_exponential_backoff_progression(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        @retry(attempts=4, initial_delay=1.0, backoff=2.0, max_delay=60.0)
        def f():
            raise RuntimeError("x")
        with pytest.raises(RuntimeError):
            f()
        assert sleeps == [1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# download_url
# ---------------------------------------------------------------------------

class TestDownloadUrl:

    def _fake_response(self, body: bytes, content_length: bool = True):
        cm = MagicMock()
        chunks = [body[i:i+64] for i in range(0, len(body), 64)] + [b""]
        cm.read = MagicMock(side_effect=chunks)
        cm.headers = MagicMock()
        if content_length:
            cm.headers.get = MagicMock(return_value=str(len(body)))
        else:
            cm.headers.get = MagicMock(return_value=None)
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    def test_happy_path_writes_file(self, tmp_path):
        body = b"x" * 200
        opener = MagicMock(return_value=self._fake_response(body))
        out = download_url("http://x", tmp_path / "out.bin", _opener=opener)
        assert out.read_bytes() == body

    def test_content_length_mismatch_detected(self, tmp_path, monkeypatch):
        # Truncation is treated as transient (could be a flaky connection),
        # so download_url retries.  Disable retries here to test the
        # detection logic in isolation.
        monkeypatch.setattr(time, "sleep", lambda s: None)
        body = b"x" * 100

        def opener(req, timeout=None):
            cm = self._fake_response(body)
            cm.headers.get = MagicMock(return_value="1000")  # lies
            return cm

        with pytest.raises(DownloadError, match="truncated"):
            download_url(
                "http://x", tmp_path / "out.bin",
                attempts=1, _opener=opener,
            )
        # Partial file cleaned up
        assert not (tmp_path / "out.bin").exists()

    def test_5xx_triggers_retry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        body = b"x" * 100

        attempts = [0]
        def opener(req, timeout=None):
            attempts[0] += 1
            if attempts[0] < 3:
                raise urllib.error.HTTPError(
                    "http://x", 503, "Service Unavailable", {}, None,
                )
            return self._fake_response(body)

        out = download_url(
            "http://x", tmp_path / "out.bin",
            attempts=5, _opener=opener,
        )
        assert out.read_bytes() == body
        assert attempts[0] == 3

    def test_4xx_fails_fast(self, tmp_path, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        attempts = [0]
        def opener(req, timeout=None):
            attempts[0] += 1
            raise urllib.error.HTTPError(
                "http://x", 404, "Not Found", {}, None,
            )
        with pytest.raises(DownloadError, match="404"):
            download_url("http://x", tmp_path / "out.bin",
                         attempts=5, _opener=opener)
        # No retries on 404
        assert attempts[0] == 1


# ---------------------------------------------------------------------------
# batched_urls
# ---------------------------------------------------------------------------

class TestBatchedUrls:

    def test_single_batch_when_short(self):
        result = list(batched_urls(
            ["a", "b", "c"],
            template="http://x.com/get/{ITEMS}",
            max_url_length=200,
        ))
        assert len(result) == 1
        url, batch = result[0]
        assert url == "http://x.com/get/a,b,c"
        assert batch == ["a", "b", "c"]

    def test_splits_when_url_would_be_too_long(self):
        items = [f"GCF_{i:09d}.1" for i in range(10)]
        result = list(batched_urls(
            items,
            template="http://x.com/get/{ITEMS}/dl",
            max_url_length=80,
        ))
        # All items present, distributed across batches
        flat = [b for _, batches in result for b in batches]
        assert flat == items
        # Every URL stays under the budget
        assert all(len(u) <= 80 for u, _ in result)
        assert len(result) > 1

    def test_empty_input_yields_nothing(self):
        assert list(batched_urls([], template="x{ITEMS}")) == []

    def test_template_must_contain_placeholder(self):
        with pytest.raises(ValueError, match=r"\{ITEMS\}"):
            list(batched_urls(["a"], template="no-place-holder"))

    def test_single_huge_item_is_single_batch(self):
        # An item alone that's larger than max_url_length still gets its
        # own batch — we don't truncate items.
        big = "x" * 200
        result = list(batched_urls(
            [big],
            template="http://x.com/{ITEMS}",
            max_url_length=50,
        ))
        assert len(result) == 1
        assert result[0][1] == [big]
