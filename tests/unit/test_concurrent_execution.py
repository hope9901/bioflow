"""Opt-in cross-stage concurrency: gather() and @pipeline(concurrent=True).

Verified against a timing backend (records each container's [start, end] and
sleeps briefly) so overlap is asserted from real intervals, not wall-clock luck.
The key guarantees:

* independent stages actually overlap,
* results are byte-identical to eager execution (same content-hash cache key),
* ``depends_on`` is honored as a real edge even when the dependency's result is
  discarded (the ``prepare_reference`` pattern).
"""
from __future__ import annotations

import threading
import time

import pytest

from bioflow import gather, pipeline, set_backend, set_workspace, stage
from bioflow.core.runner import CommandResult


class TimingBackend:
    """Records (marker, start, end) per run and sleeps, so overlap is testable."""

    def __init__(self, sleep: float = 0.25) -> None:
        self.sleep = sleep
        self.events: list[tuple[str, float, float]] = []
        self._lock = threading.Lock()

    def run(self, *, image, command, mounts, cpu, ram_gb, workdir,
            gpu=False, **_ignored) -> CommandResult:
        marker = next((m for m in ("STAGE_A", "STAGE_B", "STAGE_C",
                                    "PREP", "USE") if m in command), command[:8])
        start = time.monotonic()
        time.sleep(self.sleep)
        end = time.monotonic()
        with self._lock:
            self.events.append((marker, start, end))
        return CommandResult(exit_code=0)

    def interval(self, marker: str) -> tuple[float, float]:
        (m, s, e) = next(ev for ev in self.events if ev[0] == marker)
        return s, e


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


# ── synthetic stages (backend never runs the command, so no real tools) ──────

@stage(image="img:1", cpu=1, ram_gb=1)
def A(x, *, out_dir):
    return f"echo STAGE_A {x} > {out_dir}/a.txt"


@stage(image="img:1", cpu=1, ram_gb=1)
def B(x, *, out_dir):
    return f"echo STAGE_B {x} > {out_dir}/b.txt"


@stage(image="img:1", cpu=1, ram_gb=1, depends_on=(A, B))
def C(a, b, *, out_dir):
    return f"cat STAGE_C {a.out_dir}/a.txt {b.out_dir}/b.txt > {out_dir}/c.txt"


@pipeline(stages=[A, B, C])
def diamond_eager(x):
    a = A(x)
    b = B(x)
    return C(a, b)


@pipeline(stages=[A, B, C], concurrent=True)
def diamond_concurrent(x):
    a = A(x)
    b = B(x)
    return C(a, b)


@pytest.fixture
def timing(tmp_path):
    be = TimingBackend(sleep=0.25)
    set_backend(be)
    set_workspace(tmp_path / "ws")
    yield be
    set_backend(None)  # reset to default for later tests


def test_concurrent_independent_stages_overlap(timing):
    diamond_concurrent("p")
    a_iv, b_iv, c_iv = (timing.interval("STAGE_A"),
                        timing.interval("STAGE_B"),
                        timing.interval("STAGE_C"))
    # A and B are independent → their run intervals overlap
    assert _overlap(a_iv, b_iv), "A and B should run concurrently"
    # C depends_on (A, B) → starts only after both finish
    assert c_iv[0] >= a_iv[1] - 1e-6 and c_iv[0] >= b_iv[1] - 1e-6


def test_eager_runs_sequentially(timing):
    diamond_eager("p")
    a_iv, b_iv = timing.interval("STAGE_A"), timing.interval("STAGE_B")
    assert not _overlap(a_iv, b_iv), "eager A and B must not overlap"


def test_concurrent_result_identical_to_eager(tmp_path):
    """Same content-hash cache key ⇒ concurrency changed nothing but timing.

    Run eager then concurrent in the **same** workspace: identical keys mean the
    concurrent run is a pure cache hit on the eager one (the cache key hashes
    upstream out_dir paths, which are workspace-relative, so a shared workspace
    is the right way to compare).
    """
    from bioflow.core.runner import MockBackend
    set_backend(MockBackend())
    try:
        set_workspace(tmp_path / "ws")
        eager = diamond_eager("z")
        conc = diamond_concurrent("z")
        assert eager.cache_key and eager.cache_key == conc.cache_key
        assert eager.out_dir.name == conc.out_dir.name  # C__<same key>
        assert conc.cached, "concurrent run should hit the eager cache exactly"
    finally:
        set_backend(None)


# ── implicit depends_on: dependency result is discarded ──────────────────────

@stage(image="img:1", cpu=1, ram_gb=1)
def prep(x, *, out_dir):
    return f"touch PREP {out_dir}/index"


@stage(image="img:1", cpu=1, ram_gb=1, depends_on=prep)
def use(x, *, out_dir):
    return f"echo USE {x} > {out_dir}/o.txt"   # never receives prep's result


@pipeline(stages=[prep, use], concurrent=True)
def implicit_dep(x):
    prep(x)             # discarded — the edge is only depends_on metadata
    return use(x)


def test_concurrent_honors_discarded_depends_on(timing):
    implicit_dep("p")
    prep_iv, use_iv = timing.interval("PREP"), timing.interval("USE")
    # use must wait for prep even though prep's result was thrown away
    assert use_iv[0] >= prep_iv[1] - 1e-6, "use ran before its depends_on prep"


# ── fan-out interleaving: a fast item's downstream must not wait for a slow
#    sibling (this is what .map/.starmap returning scheduled futures buys) ────

class UnevenBackend(TimingBackend):
    """Sleeps per marker, so one fan-out item is slow and the other is fast."""

    DURATION = {"FAN_fast": 0.05, "FAN_slow": 0.60, "NEXT_fast": 0.05,
                "NEXT_slow": 0.05}

    def run(self, *, image, command, mounts, cpu, ram_gb, workdir,
            gpu=False, **_ignored) -> CommandResult:
        marker = next((m for m in self.DURATION if m in command), "other")
        start = time.monotonic()
        time.sleep(self.DURATION.get(marker, 0.02))
        end = time.monotonic()
        with self._lock:
            self.events.append((marker, start, end))
        return CommandResult(exit_code=0)


@stage(image="img:1", cpu=1, ram_gb=1)
def fan(item, *, out_dir):
    return f"run FAN_{item} > {out_dir}/{item}"


@stage(image="img:1", cpu=1, ram_gb=1, depends_on=fan)
def nxt(upstream, *, out_dir, tag="x"):
    return f"run NEXT_{tag} {upstream.out_dir} > {out_dir}/o"


@pipeline(stages=[fan, nxt], concurrent=True)
def fanout_pipe():
    ups = fan.map(["fast", "slow"])
    return nxt.starmap([((ups[0],), {"tag": "fast"}),
                        ((ups[1],), {"tag": "slow"})])


def test_fanout_interleaves_across_stages(tmp_path):
    be = UnevenBackend()
    set_backend(be)
    set_workspace(tmp_path / "ws")
    try:
        fanout_pipe()
        fast_up = be.interval("FAN_fast")
        slow_up = be.interval("FAN_slow")
        next_fast = be.interval("NEXT_fast")
        # The fast item's downstream starts while the slow sibling is still
        # running — i.e. the fan-out is not a barrier.
        assert next_fast[0] < slow_up[1], (
            "downstream of the fast item waited for the slow sibling "
            f"(next_fast start={next_fast[0]:.3f}, slow end={slow_up[1]:.3f})"
        )
        assert next_fast[0] >= fast_up[1] - 1e-6  # still after its own upstream
    finally:
        set_backend(None)


def test_gather_runs_thunks_concurrently(timing):
    results = gather(lambda: A("p"), lambda: A("q"))
    assert [r.ok for r in results] == [True, True]
    # two independent A runs (different inputs) overlapped
    ivs = [ev for ev in timing.events if ev[0] == "STAGE_A"]
    assert len(ivs) == 2 and _overlap(ivs[0][1:], ivs[1][1:])
