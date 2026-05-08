"""Phase 2G — @stage retry / fault-tolerance tests."""
from __future__ import annotations

import pytest

from bioflow import stage, set_workspace, set_backend, MockBackend
from bioflow.core.runner import CommandResult
from bioflow.sdk import _bump_resources


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    backend = MockBackend()
    set_backend(backend)
    yield backend


# ---------------------------------------------------------------------------
# _bump_resources unit
# ---------------------------------------------------------------------------

class TestBumpResources:

    def test_no_recipe_no_change(self):
        cpu, ram = _bump_resources(4, 8.0, {})
        assert (cpu, ram) == (4, 8.0)

    def test_multiplier_string(self):
        cpu, ram = _bump_resources(4, 8.0, {"ram_gb": "2x"})
        assert cpu == 4
        assert ram == 16.0

    def test_multiplier_uppercase_x(self):
        cpu, ram = _bump_resources(4, 8.0, {"ram_gb": "1.5X"})
        assert ram == 12.0

    def test_absolute_override(self):
        cpu, ram = _bump_resources(2, 4.0, {"cpu": 8, "ram_gb": 16.0})
        assert (cpu, ram) == (8, 16.0)

    def test_cpu_minimum_one(self):
        cpu, _ = _bump_resources(2, 4.0, {"cpu": "0.1x"})
        assert cpu >= 1

    def test_unknown_key_ignored(self):
        cpu, ram = _bump_resources(4, 8.0, {"disk_gb": "2x"})
        # Unrecognised keys are warned about but don't crash
        assert (cpu, ram) == (4, 8.0)

    def test_invalid_value_falls_through(self):
        cpu, ram = _bump_resources(4, 8.0, {"ram_gb": "garbage"})
        # Bad value is logged, original kept
        assert (cpu, ram) == (4, 8.0)


# ---------------------------------------------------------------------------
# Retry on failure
# ---------------------------------------------------------------------------

class TestStageRetry:

    def _make_flaky_backend(self, fail_first_n: int = 1):
        """Backend that fails the first N calls, then succeeds."""
        class Flaky:
            def __init__(self):
                self.calls = []

            def run(self, **kw):
                self.calls.append(dict(kw))
                if len(self.calls) <= fail_first_n:
                    return CommandResult(exit_code=1, stderr=f"flake #{len(self.calls)}")
                return CommandResult(exit_code=0)
        return Flaky()

    def test_retry_zero_no_retry(self):
        be = self._make_flaky_backend(fail_first_n=2)
        set_backend(be)

        @stage(image="x:1", cache=False, retry=0)
        def s(x):
            return f"echo {x}"

        r = s("a")
        assert not r.ok
        assert len(be.calls) == 1   # no retries

    def test_retry_succeeds_after_flake(self):
        be = self._make_flaky_backend(fail_first_n=2)
        set_backend(be)

        @stage(image="x:1", cache=False, retry=3)
        def s(x):
            return f"echo {x}"

        r = s("a")
        assert r.ok
        assert len(be.calls) == 3   # 2 fails + 1 success

    def test_retry_exhausted_returns_failure(self):
        be = self._make_flaky_backend(fail_first_n=99)   # always fail
        set_backend(be)

        @stage(image="x:1", cache=False, retry=2)
        def s(x):
            return f"echo {x}"

        r = s("a")
        assert not r.ok
        # 1 + 2 retries = 3 total attempts
        assert len(be.calls) == 3

    def test_success_first_try_no_extra_calls(self):
        be = MockBackend()
        set_backend(be)

        @stage(image="x:1", cache=False, retry=5)
        def s(x):
            return f"echo {x}"

        s("a")
        # Only 1 call even though retry=5 was allowed
        assert len(be.calls) == 1


# ---------------------------------------------------------------------------
# Resource bumping per attempt
# ---------------------------------------------------------------------------

class TestResourceBumpDuringRetry:

    def _record_resources_backend(self, fail_first_n=2):
        """Backend that captures cpu/ram_gb for each call and fails N times."""
        class Recorder:
            def __init__(self):
                self.calls = []
            def run(self, **kw):
                self.calls.append((kw["cpu"], kw["ram_gb"]))
                if len(self.calls) <= fail_first_n:
                    return CommandResult(exit_code=1, stderr="oom")
                return CommandResult(exit_code=0)
        return Recorder()

    def test_ram_doubled_each_retry(self):
        be = self._record_resources_backend(fail_first_n=2)
        set_backend(be)

        @stage(image="x:1", cache=False,
               cpu=2, ram_gb=4.0,
               retry=3, retry_with={"ram_gb": "2x"})
        def s(x): return f"echo {x}"

        s("a")
        # First call: 4 GB; second: 8 GB; third: 16 GB
        rams = [c[1] for c in be.calls]
        assert rams == [4.0, 8.0, 16.0]

    def test_cpu_absolute_override(self):
        be = self._record_resources_backend(fail_first_n=1)
        set_backend(be)

        @stage(image="x:1", cache=False,
               cpu=2, ram_gb=4.0,
               retry=2, retry_with={"cpu": 16})
        def s(x): return f"echo {x}"

        s("a")
        cpus = [c[0] for c in be.calls]
        assert cpus[0] == 2
        assert cpus[1] == 16

    def test_no_bump_without_retry_with(self):
        be = self._record_resources_backend(fail_first_n=1)
        set_backend(be)

        @stage(image="x:1", cache=False,
               cpu=2, ram_gb=4.0, retry=2)
        def s(x): return f"echo {x}"

        s("a")
        rams = [c[1] for c in be.calls]
        assert rams == [4.0, 4.0]


# ---------------------------------------------------------------------------
# Cache interaction — successful retry should still cache
# ---------------------------------------------------------------------------

class TestRetryCacheInteraction:

    def test_successful_retry_writes_cache(self, tmp_path):
        class Flaky:
            def __init__(self): self.calls = 0
            def run(self, **kw):
                self.calls += 1
                if self.calls == 1:
                    return CommandResult(exit_code=1, stderr="first try fail")
                return CommandResult(exit_code=0)
        be = Flaky()
        set_backend(be)

        @stage(image="x:1", cache=True, retry=2)
        def s(x): return f"echo {x}"

        r1 = s("a")
        assert r1.ok and r1.cached is False
        assert be.calls == 2

        # Second invocation must be cached → 0 backend calls
        r2 = s("a")
        assert r2.ok and r2.cached is True
        assert be.calls == 2

    def test_failed_retry_does_not_poison_cache(self, tmp_path):
        class AlwaysFail:
            def __init__(self): self.calls = 0
            def run(self, **kw):
                self.calls += 1
                return CommandResult(exit_code=1, stderr="boom")
        be = AlwaysFail()
        set_backend(be)

        @stage(image="x:1", cache=True, retry=2)
        def s(x): return f"echo {x}"

        r1 = s("a")
        assert not r1.ok
        # 1 + 2 retries = 3 calls
        assert be.calls == 3

        # Re-running goes through retries again, NOT cached as success
        r2 = s("a")
        assert not r2.ok
        assert be.calls == 6
