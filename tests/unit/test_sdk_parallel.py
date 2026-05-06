"""Phase 1B — auto-parallelism, progress, starmap, imap_unordered tests."""
from __future__ import annotations

import os
import time
from unittest.mock import MagicMock

import pytest

from bioflow import stage, set_workspace, set_backend, MockBackend
from bioflow.sdk import _resolve_parallel, _AnsiProgress


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    backend = MockBackend()
    set_backend(backend)
    yield backend


# ---------------------------------------------------------------------------
# parallel="auto" resolution
# ---------------------------------------------------------------------------

class TestParallelResolution:

    def test_int_passes_through(self):
        assert _resolve_parallel(4, 2) == 4
        assert _resolve_parallel(1, 2) == 1
        assert _resolve_parallel(99, 1) == 99

    def test_zero_clamps_to_one(self):
        assert _resolve_parallel(0, 2) == 1
        assert _resolve_parallel(-5, 2) == 1

    def test_auto_fills_host_cpu(self, monkeypatch):
        monkeypatch.setattr(os, "cpu_count", lambda: 12)
        assert _resolve_parallel("auto", 1) == 12
        assert _resolve_parallel("auto", 2) == 6
        assert _resolve_parallel("auto", 4) == 3
        assert _resolve_parallel("auto", 8) == 1

    def test_auto_clamps_to_one_minimum(self, monkeypatch):
        monkeypatch.setattr(os, "cpu_count", lambda: 4)
        # cpu_per_stage > host → still gets 1, never 0
        assert _resolve_parallel("auto", 16) == 1

    def test_auto_handles_missing_cpu_count(self, monkeypatch):
        monkeypatch.setattr(os, "cpu_count", lambda: None)
        assert _resolve_parallel("auto", 2) == 1

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError, match="parallel must be int or 'auto'"):
            _resolve_parallel("crazy", 2)


# ---------------------------------------------------------------------------
# starmap
# ---------------------------------------------------------------------------

class TestStarmap:

    def test_starmap_two_positional_args(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def add(a, b):
            return f"echo {a}+{b}"

        results = add.starmap([(1, 2), (3, 4), (5, 6)])
        assert len(results) == 3
        assert all(r.ok for r in results)
        commands = [c["command"] for c in _isolated_runtime.calls]
        assert "echo 1+2" in commands
        assert "echo 3+4" in commands

    def test_starmap_args_kwargs_form(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def go(x, *, mode):
            return f"echo {x} mode={mode}"

        results = go.starmap([
            ((1,), {"mode": "fast"}),
            ((2,), {"mode": "slow"}),
        ])
        assert len(results) == 2
        cmds = [c["command"] for c in _isolated_runtime.calls]
        assert "echo 1 mode=fast" in cmds
        assert "echo 2 mode=slow" in cmds

    def test_starmap_parallel_auto(self, _isolated_runtime, monkeypatch):
        monkeypatch.setattr(os, "cpu_count", lambda: 8)

        @stage(image="busybox:latest", cpu=2, cache=False)
        def go(a, b):
            return f"echo {a} {b}"

        results = go.starmap([(i, i + 1) for i in range(10)], parallel="auto")
        assert len(results) == 10


# ---------------------------------------------------------------------------
# imap_unordered
# ---------------------------------------------------------------------------

class TestImapUnordered:

    def test_imap_yields_results_as_completed(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def go(x):
            return f"echo {x}"

        gen = go.imap_unordered([1, 2, 3, 4, 5], parallel=2)
        results = list(gen)
        assert len(results) == 5
        assert all(r.ok for r in results)

    def test_imap_serial_preserves_order(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def go(x):
            return f"echo {x}"

        results = list(go.imap_unordered([10, 20, 30], parallel=1))
        # Serial mode: yield in submission order
        cmds = [r.command for r in results]
        assert cmds == ["echo 10", "echo 20", "echo 30"]


# ---------------------------------------------------------------------------
# progress callback
# ---------------------------------------------------------------------------

class TestProgressCallback:

    def test_callable_progress_invoked_per_completion(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def go(x):
            return f"echo {x}"

        cb = MagicMock()
        results = go.map([1, 2, 3], parallel=1, progress=cb)
        assert cb.call_count == 3
        # Last call should report (3, 3, last_result)
        last_done, last_total, last_sr = cb.call_args[0]
        assert last_done == 3 and last_total == 3
        assert last_sr.ok

    def test_progress_true_does_not_crash(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def go(x):
            return f"echo {x}"

        # Just ensure it runs cleanly with the built-in ANSI bar
        results = go.map([1, 2, 3], parallel=2, progress=True)
        assert all(r.ok for r in results)

    def test_progress_false_no_output(
        self, _isolated_runtime, capsys,
    ):
        @stage(image="busybox:latest", cache=False)
        def go(x):
            return f"echo {x}"

        go.map([1, 2, 3], parallel=2, progress=False)
        out = capsys.readouterr()
        # No bar characters in stderr
        assert "###" not in out.err

    def test_progress_callback_sees_cached_flag(
        self, _isolated_runtime,
    ):
        @stage(image="busybox:latest")  # cache=True default
        def go(x):
            return f"echo {x}"

        # Warm the cache
        go.map([1, 2, 3], parallel=1)

        cb = MagicMock()
        go.map([1, 2, 3], parallel=1, progress=cb)
        # All three should be cache hits
        cached_flags = [call.args[2].cached for call in cb.call_args_list]
        assert all(cached_flags)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_input(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def go(x):
            return f"echo {x}"

        assert go.map([]) == []
        assert go.starmap([]) == []
        assert list(go.imap_unordered([])) == []
        assert len(_isolated_runtime.calls) == 0

    def test_map_preserves_input_order(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def go(x):
            return f"echo {x}"

        results = go.map([5, 1, 3, 2, 4], parallel=4)
        cmds = [r.command for r in results]
        assert cmds == ["echo 5", "echo 1", "echo 3", "echo 2", "echo 4"]


# ---------------------------------------------------------------------------
# AnsiProgress unit
# ---------------------------------------------------------------------------

class TestAnsiProgress:

    def test_counts_cached_and_failed(self):
        from bioflow.sdk import StageResult
        from pathlib import Path

        bar = _AnsiProgress("test", total=4)
        ok       = StageResult("s", Path("/tmp"), "x", 0, cached=False)
        cached   = StageResult("s", Path("/tmp"), "x", 0, cached=True)
        failed   = StageResult("s", Path("/tmp"), "x", 1, cached=False)

        bar(1, 4, ok)
        bar(2, 4, cached)
        bar(3, 4, failed)
        bar(4, 4, ok)

        assert bar.cached == 1
        assert bar.failed == 1
