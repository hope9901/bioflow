"""Opt-in cross-stage concurrency for pipelines.

The default execution model is eager: a recipe body is plain Python, and each
``Stage.__call__`` runs its container and blocks until it finishes.  Independent
stages therefore never overlap.

This module adds two opt-in ways to overlap independent work **without changing
recipe bodies or the content-addressed cache** (out_dir is hashed from inputs,
so results are identical no matter the execution order):

* ``gather(thunk_a, thunk_b, ...)`` — run independent stage calls concurrently
  and return their results in order (option B: explicit, small, safe).

* ``@pipeline(concurrent=True)`` — implicit futures (option C).  Inside a
  concurrent pipeline, ``Stage.__call__`` submits the work to a resource-aware
  scheduler and returns a :class:`FutureStageResult` immediately; a downstream
  stage blocks only when it actually reads an upstream's ``out_dir``.  Sibling
  stages with no dependency between them run at the same time.

Correctness guarantees baked in:

* **``depends_on`` is honored as a real ordering edge**, not just metadata — so
  a stage whose dependency is implicit (e.g. ``prepare_reference`` indexes a
  shared file that ``align`` then reads without receiving its result) still
  waits for it.
* **Deadlock-free**: a task is submitted to the pool only after all its upstream
  futures have completed, so a pool worker never blocks waiting on an upstream.
* **No cache races**: identical cache keys are serialized by a per-key lock, so
  two identical stages can't write the same ``.cache`` dir at once.
* **No resource oversubscription**: a cpu-unit budget gates how many stages run
  concurrently.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any, Callable, Optional

from bioflow.core.logger import get_logger

log = get_logger()

_current: "ContextVar[Optional[Scheduler]]" = ContextVar(
    "bioflow_scheduler", default=None
)


def active_scheduler() -> "Optional[Scheduler]":
    """The scheduler for the pipeline currently executing, or None (eager)."""
    return _current.get()


def _backend_schedules_remotely() -> bool:
    """True when the active backend queues work on a cluster (e.g. Slurm).

    Peeks at the already-configured backend rather than constructing one, so
    building a Scheduler never has side effects.
    """
    try:
        from bioflow.sdk import _runtime  # noqa: PLC0415
        return bool(getattr(_runtime._active_backend, "_REMOTE_SCHEDULING", False))
    except Exception:  # pragma: no cover - defensive
        return False


# ---------------------------------------------------------------------------
# Lazy result handle
# ---------------------------------------------------------------------------

class FutureStageResult:
    """A stand-in for a :class:`StageResult` that is still running.

    Reading any attribute (``out_dir``, ``ok``, …) blocks until the stage
    finishes, so recipe bodies use it exactly like a real ``StageResult``.
    """

    __slots__ = ("_future",)

    def __init__(self, future: "Future") -> None:
        self._future = future

    def result(self):
        return self._future.result()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._future.result(), name)


def _resolve(v: Any) -> Any:
    """Replace any FutureStageResult (incl. nested in list/tuple/dict) values."""
    if isinstance(v, FutureStageResult):
        return v.result()
    if isinstance(v, list):
        return [_resolve(x) for x in v]
    if isinstance(v, tuple):
        return tuple(_resolve(x) for x in v)
    if isinstance(v, dict):
        return {k: _resolve(x) for k, x in v.items()}
    return v


def _collect_futures(v: Any, into: set) -> None:
    if isinstance(v, FutureStageResult):
        into.add(v._future)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _collect_futures(x, into)


# ---------------------------------------------------------------------------
# Resource gate — a counting semaphore over "cpu units"
# ---------------------------------------------------------------------------

class _ResourceGate:
    def __init__(self, budget: int) -> None:
        self._budget = max(1, budget)
        self._avail = self._budget
        self._cv = threading.Condition()

    def acquire(self, n: int) -> int:
        n = max(1, min(int(n), self._budget))
        with self._cv:
            while self._avail < n:
                self._cv.wait()
            self._avail -= n
        return n

    def release(self, n: int) -> None:
        with self._cv:
            self._avail += n
            self._cv.notify_all()


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """Dependency-aware, resource-gated executor for one concurrent pipeline run."""

    #: In-flight job cap when the backend schedules remotely (Slurm & co.).
    #: The cluster does the real queuing, so gating on local cores would
    #: throttle submissions to a machine that isn't running the work.
    REMOTE_INFLIGHT = 64

    def __init__(self, cpu_budget: Optional[int] = None,
                 max_workers: Optional[int] = None) -> None:
        if cpu_budget is None:
            cpu_budget = (self.REMOTE_INFLIGHT if _backend_schedules_remotely()
                          else (os.cpu_count() or 2))
        self._cpu_budget = cpu_budget
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers or max(2, self._cpu_budget)
        )
        self._gate = _ResourceGate(self._cpu_budget)
        self._stage_futures: "dict[Any, list[Future]]" = {}
        self._all: "list[Future]" = []
        self._lock = threading.Lock()
        self._keylocks: "dict[str, threading.Lock]" = {}
        self._keylocks_guard = threading.Lock()

    # -- future bookkeeping (for depends_on wiring) --
    def _futures_for(self, stage) -> "list[Future]":
        with self._lock:
            return list(self._stage_futures.get(stage, []))

    def _register(self, stage, fut: "Future") -> None:
        with self._lock:
            self._stage_futures.setdefault(stage, []).append(fut)
            self._all.append(fut)

    def _keylock(self, key: str) -> "threading.Lock":
        with self._keylocks_guard:
            lk = self._keylocks.get(key)
            if lk is None:
                lk = self._keylocks[key] = threading.Lock()
            return lk

    def _upstreams(self, stage, args: tuple, kwargs: dict) -> set:
        """Futures this call must wait for.

        Two kinds of edge:

        * **explicit** — a result passed in as an argument.  That future *is*
          the dependency, precisely.
        * **implicit** — a ``depends_on`` stage whose result was never passed
          (e.g. ``prepare_reference`` just indexes a shared file).  There is
          nothing in the args to key on, so wait for all of its invocations.

        A ``depends_on`` stage that *did* supply an argument is deliberately
        skipped: waiting for its other invocations too would turn a fan-out
        into a barrier, so a fast item's downstream could never start while a
        slow sibling is still running.
        """
        arg_futs: set = set()
        for a in args:
            _collect_futures(a, arg_futs)
        for v in kwargs.values():
            _collect_futures(v, arg_futs)

        ups: set = set(arg_futs)
        for dep in getattr(stage, "depends_on", ()):
            dep_futs = set(self._futures_for(dep))
            if dep_futs & arg_futs:
                continue          # precise edge already captured by the args
            ups.update(dep_futs)  # implicit dependency — wait for all of it
        return ups

    def submit_call(self, stage, run_once: Callable, args: tuple,
                    kwargs: dict) -> FutureStageResult:
        """Schedule ``run_once(resolved_args, resolved_kwargs)`` for *stage*."""
        ups = self._upstreams(stage, args, kwargs)
        result_fut: "Future" = Future()

        def launch() -> None:
            try:
                r_args = tuple(_resolve(a) for a in args)
                r_kwargs = {k: _resolve(v) for k, v in kwargs.items()}
                key = ""
                try:
                    key = stage._cache_key_for(r_args, r_kwargs)
                except Exception:  # pragma: no cover - keylock is best-effort
                    key = ""
                n = self._gate.acquire(getattr(stage, "cpu", 1))
                try:
                    if key:
                        with self._keylock(key):
                            sr = run_once(r_args, r_kwargs)
                    else:
                        sr = run_once(r_args, r_kwargs)
                finally:
                    self._gate.release(n)
                result_fut.set_result(sr)
            except BaseException as exc:  # noqa: BLE001 - propagate to reader
                result_fut.set_exception(exc)

        self._schedule_after(ups, launch)
        self._register(stage, result_fut)
        return FutureStageResult(result_fut)

    def _schedule_after(self, ups: set, launch: Callable) -> None:
        pending = [u for u in ups if u is not None and not u.done()]
        if not pending:
            self._pool.submit(launch)
            return
        state = {"n": len(pending)}
        lk = threading.Lock()

        def done_cb(_f) -> None:
            with lk:
                state["n"] -= 1
                ready = state["n"] == 0
            if ready:
                self._pool.submit(launch)

        for u in pending:
            u.add_done_callback(done_cb)

    def join(self) -> None:
        """Wait for every scheduled stage; re-raises the first failure."""
        for f in list(self._all):
            f.result()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Option B — explicit gather
# ---------------------------------------------------------------------------

def gather(*thunks: Callable[[], Any]) -> list:
    """Run independent stage-calling ``thunks`` concurrently; return results
    in argument order.

    Each thunk is a zero-arg callable that performs one (or more) stage calls,
    e.g. ``gather(lambda: align(a, ref), lambda: align(b, ref))``.  Safe for
    *independent* work — the content-addressed cache keeps results identical to
    running them one after another.
    """
    if len(thunks) <= 1:
        return [t() for t in thunks]
    with ThreadPoolExecutor(max_workers=len(thunks)) as pool:
        futs = [pool.submit(t) for t in thunks]
        return [f.result() for f in futs]
