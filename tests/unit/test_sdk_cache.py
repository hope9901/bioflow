"""Phase 1C — input-hash caching tests for the @stage decorator.

Each test uses the MockBackend so we can count exact backend calls.
A cache HIT must NOT call the backend at all.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bioflow import (
    stage,
    set_workspace,
    set_backend,
    set_cache_enabled,
    is_cache_enabled,
    clear_cache,
    MockBackend,
)


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    backend = MockBackend()
    set_backend(backend)
    set_cache_enabled(True)   # default; reset between tests
    yield backend
    set_cache_enabled(True)


# ---------------------------------------------------------------------------
# Basic hit / miss
# ---------------------------------------------------------------------------

class TestBasicHitMiss:

    def test_second_identical_call_is_cache_hit(self, _isolated_runtime):
        backend = _isolated_runtime

        @stage(image="busybox:latest")
        def echo(name):
            return f"echo {name}"

        r1 = echo("dickeya")
        r2 = echo("dickeya")

        assert r1.cached is False
        assert r2.cached is True
        assert r1.out_dir == r2.out_dir          # cached run reuses dir
        assert len(backend.calls) == 1            # backend only called once
        assert r1.cache_key == r2.cache_key
        assert len(r1.cache_key) == 24

    def test_different_arg_misses_cache(self, _isolated_runtime):
        backend = _isolated_runtime

        @stage(image="busybox:latest")
        def echo(name):
            return f"echo {name}"

        echo("dickeya")
        echo("pectobacterium")

        assert len(backend.calls) == 2

    def test_cache_hit_skips_backend_entirely(self, _isolated_runtime):
        @stage(image="busybox:latest")
        def echo(name):
            return f"echo {name}"

        echo("x")
        backend = _isolated_runtime
        before = len(backend.calls)
        for _ in range(50):
            echo("x")
        after = len(backend.calls)
        assert after == before, "cached calls must not invoke the backend"


# ---------------------------------------------------------------------------
# Per-argument invalidation
# ---------------------------------------------------------------------------

class TestArgumentInvalidation:

    def test_file_mtime_change_invalidates_cache(
        self, _isolated_runtime, tmp_path,
    ):
        backend = _isolated_runtime
        ws = tmp_path / "ws"
        f = ws / "data.txt"
        f.write_text("v1")

        @stage(image="busybox:latest")
        def cat(path):
            return f"cat {path}"

        cat(f)
        # Change mtime by writing the same content but later
        time.sleep(0.02)
        os.utime(f, (time.time() + 1, time.time() + 1))
        cat(f)

        assert len(backend.calls) == 2

    def test_file_content_change_invalidates_cache(
        self, _isolated_runtime, tmp_path,
    ):
        backend = _isolated_runtime
        ws = tmp_path / "ws"
        f = ws / "data.txt"
        f.write_text("first version")

        @stage(image="busybox:latest")
        def cat(path):
            return f"cat {path}"

        cat(f)
        f.write_text("a different content of the same length-ish")
        cat(f)
        assert len(backend.calls) == 2

    def test_kwarg_change_invalidates_cache(self, _isolated_runtime):
        backend = _isolated_runtime

        @stage(image="busybox:latest")
        def go(*, mode):
            return f"echo {mode}"

        go(mode="fast")
        go(mode="slow")
        go(mode="fast")   # back to fast - should hit cache
        assert len(backend.calls) == 2

    def test_list_arg_invalidates_cache(self, _isolated_runtime):
        backend = _isolated_runtime

        @stage(image="busybox:latest")
        def join_(items):
            return f"echo {' '.join(items)}"

        join_(["a", "b"])
        join_(["a", "b"])         # hit
        join_(["a", "b", "c"])    # miss
        assert len(backend.calls) == 2


# ---------------------------------------------------------------------------
# Stage-definition-level invalidation
# ---------------------------------------------------------------------------

class TestStageDefinitionInvalidation:

    def test_image_change_invalidates_cache(self, _isolated_runtime):
        # Define the same logical stage with different images
        @stage(image="busybox:1.36")
        def go(x): return f"echo {x}"

        go("v")

        @stage(image="busybox:1.37")
        def go(x): return f"echo {x}"

        go("v")
        assert len(_isolated_runtime.calls) == 2

    def test_cpu_change_invalidates_cache(self, _isolated_runtime):
        @stage(image="busybox:latest", cpu=2)
        def go(x): return f"echo {x}"
        go("v")

        @stage(image="busybox:latest", cpu=4)
        def go(x): return f"echo {x}"
        go("v")
        assert len(_isolated_runtime.calls) == 2

    def test_builder_source_change_invalidates_cache(self, _isolated_runtime):
        @stage(image="busybox:latest")
        def go(x): return f"echo old: {x}"
        go("v")

        @stage(image="busybox:latest")
        def go(x): return f"echo new: {x}"
        go("v")
        assert len(_isolated_runtime.calls) == 2


# ---------------------------------------------------------------------------
# Failure semantics — failed runs must not poison the cache
# ---------------------------------------------------------------------------

class TestFailureNoPoisoning:

    def test_failed_run_not_cached(self):
        from bioflow.sdk import set_backend
        from bioflow.core.runner import CommandResult

        class FlakyBackend:
            def __init__(self): self.n = 0
            def run(self, **kw):
                self.n += 1
                # Fail the first time, succeed the second
                if self.n == 1:
                    return CommandResult(exit_code=1, stderr="boom")
                return CommandResult(exit_code=0)

        be = FlakyBackend()
        set_backend(be)

        @stage(image="busybox:latest")
        def go(x): return f"echo {x}"

        r1 = go("v")
        assert not r1.ok and r1.cached is False
        r2 = go("v")
        # Second call must re-execute (cache must NOT have a sentinel)
        assert r2.ok
        assert be.n == 2


# ---------------------------------------------------------------------------
# Disable / clear
# ---------------------------------------------------------------------------

class TestDisableAndClear:

    def test_per_stage_cache_off(self, _isolated_runtime):
        @stage(image="busybox:latest", cache=False)
        def always(x): return f"echo {x}"

        always("v"); always("v"); always("v")
        assert len(_isolated_runtime.calls) == 3

    def test_global_disable(self, _isolated_runtime):
        @stage(image="busybox:latest")
        def go(x): return f"echo {x}"

        set_cache_enabled(False)
        assert is_cache_enabled() is False
        go("v"); go("v"); go("v")
        assert len(_isolated_runtime.calls) == 3
        # Re-enable for further tests
        set_cache_enabled(True)

    def test_clear_cache_forces_reexecution(self, _isolated_runtime, tmp_path):
        @stage(image="busybox:latest")
        def go(x): return f"echo {x}"

        go("v")
        go("v")              # hit
        assert len(_isolated_runtime.calls) == 1

        n = clear_cache(tmp_path / "ws")
        assert n >= 1

        go("v")              # miss again
        assert len(_isolated_runtime.calls) == 2

    def test_env_var_disables_cache(self, monkeypatch, tmp_path):
        # The env var is consulted at module import time, so we re-import.
        import importlib
        import bioflow.sdk as sdk_mod
        monkeypatch.setenv("BIOFLOW_NO_CACHE", "1")
        importlib.reload(sdk_mod)
        assert sdk_mod._cache_enabled is False
        # Restore default for downstream tests
        monkeypatch.delenv("BIOFLOW_NO_CACHE", raising=False)
        importlib.reload(sdk_mod)
        # Re-bind the package-level export so other tests see the fresh symbols
        import bioflow
        importlib.reload(bioflow)


# ---------------------------------------------------------------------------
# Map + cache interaction
# ---------------------------------------------------------------------------

class TestMapWithCache:

    def test_map_partial_cache_only_runs_new_inputs(self, _isolated_runtime):
        backend = _isolated_runtime

        @stage(image="busybox:latest")
        def go(x): return f"echo {x}"

        go.map(["a", "b", "c"])
        assert len(backend.calls) == 3

        # Add a new element; existing 3 should hit cache.
        go.map(["a", "b", "c", "d"])
        assert len(backend.calls) == 4   # only 'd' was new

    def test_map_all_cached_zero_backend_calls(self, _isolated_runtime):
        backend = _isolated_runtime

        @stage(image="busybox:latest")
        def go(x): return f"echo {x}"

        go.map(["a", "b", "c"])
        before = len(backend.calls)
        go.map(["a", "b", "c"])
        assert len(backend.calls) == before
