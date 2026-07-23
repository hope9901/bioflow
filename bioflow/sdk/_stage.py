"""Stage class, @stage decorator, and the fan-out execution engine.

This is the largest single piece of the SDK; everything else in
``bioflow.sdk`` exists to keep this file readable.
"""
from __future__ import annotations

import functools
import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional, Union, cast

from bioflow.core import provenance as _prov
from bioflow.core.logger import get_logger
from bioflow.core.runner import CommandResult

from bioflow.sdk._cache import CACHE_SENTINEL, is_cache_enabled, is_log_streaming_enabled
from bioflow.sdk._concurrent import active_scheduler
from bioflow.sdk._hashing import _compute_cache_key
from bioflow.sdk._parallel import (
    _AnsiProgress,
    _ProgressCallback,
    _bump_resources,
    _resolve_parallel,
)
from bioflow.sdk._paths import (
    _CONTAINER_WORKSPACE,
    _apply_external_translation,
    _collect_external_mounts,
    _translate_command,
)
from bioflow.sdk._result import StageResult
from bioflow.sdk._runtime import (
    _get_backend,
    _get_param_overrides,
    _get_workspace,
    _next_run_id,
)

log = get_logger()


def _coerce_scalar(v: Any) -> Any:
    """Coerce a string override value to int/float when it clearly is one;
    leave everything else (incl. comma lists like ``21,33,55``) as text."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s.lstrip("-").isdigit():
        return int(s)
    try:
        return float(s)
    except ValueError:
        return v


def _apply_param_overrides(stage_name: str, func: Callable, kwargs: dict) -> dict:
    """Overlay ``--set`` overrides onto a stage's keyword-only parameters.

    Only keyword-only params are touched (the bioflow convention puts tunable
    knobs after ``*``; data dependencies stay positional), so an override can
    never collide with a positional argument.  ``<stage>.<param>`` beats a
    bare ``<param>``.  Applied before cache-key + provenance so both see it.
    """
    overrides = _get_param_overrides()
    if not overrides:
        return kwargs
    applied: dict = {}
    for pname, p in inspect.signature(func).parameters.items():
        if p.kind is not inspect.Parameter.KEYWORD_ONLY or pname == "out_dir":
            continue
        if f"{stage_name}.{pname}" in overrides:
            applied[pname] = _coerce_scalar(overrides[f"{stage_name}.{pname}"])
        elif pname in overrides:
            applied[pname] = _coerce_scalar(overrides[pname])
    if applied:
        log.info(f"OVERRIDE stage={stage_name}  {applied}")
        return {**kwargs, **applied}
    return kwargs


def _input_dirs(args: tuple, kwargs: dict) -> "list[str]":
    """Upstream ``out_dir`` paths this call reads.

    Only consumed by backends that stage I/O for a worker which can't see the
    workspace — they need to know what to ship out.  Walks args/kwargs
    including the lists a fan-out produces.
    """
    found: "list[str]" = []
    seen: set = set()

    def walk(v: Any) -> None:
        out = getattr(v, "out_dir", None)
        if out is not None and not isinstance(v, (str, bytes, Path)):
            s = str(out)
            if s not in seen:
                seen.add(s)
                found.append(s)
            return
        if isinstance(v, (list, tuple, set)):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    for a in args:
        walk(a)
    for v in kwargs.values():
        walk(v)
    return found


# ---------------------------------------------------------------------------
# Stage object
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Stage:
    """A wrapped function that, when called, runs a container.

    Use :func:`stage` as a decorator rather than instantiating directly.

    Caching
    -------
    When ``cache=True`` (default), the SDK computes a deterministic key from
    (image, cpu, ram_gb, builder source, every input argument's content
    hash) and reuses the previous out_dir if a sentinel file is present.
    Set ``cache=False`` per stage, or call ``set_cache_enabled(False)`` to
    disable globally, or set the env var ``BIOFLOW_NO_CACHE=1`` at process
    start.
    """
    name: str
    func: Callable[..., str]
    image: str
    cpu: int = 2
    ram_gb: float = 4.0
    gpu: bool = False
    """Request all host GPUs for this stage's container (Docker
    ``--gpus all`` equivalent).  Needs the NVIDIA Container Toolkit on
    the host; ignored with a warning on CPU-only hosts."""
    description: str = ""
    cache: bool = True
    depends_on: tuple = ()
    """Stages whose results feed this stage.  Pure metadata — does not
    automatically wire output→input.  Used by ``@pipeline`` decorators
    to build a DAG diagram for ``show_graph()`` and ``dry_run()``."""

    retry: int = 0
    """Number of additional attempts after a non-zero exit code.
    ``retry=0`` (default) means no retries — fail-fast.  ``retry=3``
    runs the stage up to 4 times total."""

    retry_with: dict = field(default_factory=dict)
    """Per-attempt resource bumps.  Supports the syntax ``"2x"`` for a
    multiplier or a numeric absolute.  Currently understood keys:
    ``cpu``, ``ram_gb``.  Example: ``retry_with={"ram_gb": "2x"}`` makes
    every retry double the RAM allocated to the container — useful when
    the failure mode is OOM.  Untouched if ``retry == 0``."""

    # ------------------------------------------------------------------
    # Single-call execution
    # ------------------------------------------------------------------
    def __call__(self, *args: Any, **kwargs: Any) -> StageResult:
        sched = active_scheduler()
        if sched is not None:
            # Concurrent pipeline: submit and return a lazy handle that blocks
            # only when a downstream stage reads it.
            return cast(StageResult,
                        sched.submit_call(self, self._run_once, args, kwargs))
        return self._run_once(args, kwargs)

    def _cache_key_for(self, args: tuple, kwargs: dict) -> str:
        """The cache key this call would use (``""`` when caching is off).

        Read-only — the concurrent scheduler uses it to serialize two stages
        that would write the same ``.cache`` dir.
        """
        if not (self.cache and is_cache_enabled()):
            return ""
        kwargs = _apply_param_overrides(self.name, self.func, kwargs)
        return _compute_cache_key(self, args, kwargs)

    def _run_once(self, args: tuple, kwargs: dict) -> StageResult:
        workspace = _get_workspace()
        started_at = _prov._now_iso()

        # Apply `--set` parameter overrides up front so the cache key and
        # provenance both reflect them (and the rendered command uses them).
        kwargs = _apply_param_overrides(self.name, self.func, kwargs)

        # ------------------------- cache lookup -------------------------
        cache_key = ""
        cache_dir: Optional[Path] = None
        cache_active = self.cache and is_cache_enabled()
        if cache_active:
            cache_key = _compute_cache_key(self, args, kwargs)
            cache_dir = workspace / ".cache" / f"{self.name}__{cache_key}"
            sentinel = cache_dir / CACHE_SENTINEL
            if sentinel.exists():
                log.info(
                    f"CACHE HIT  stage={self.name}  key={cache_key[:8]}"
                )
                _prov.record_stage(
                    name=self.name, image=self.image, command="(cached)",
                    exit_code=0, cached=True, out_dir=cache_dir,
                    started_at=started_at, ended_at=_prov._now_iso(),
                    args=args, kwargs=kwargs,
                )
                return StageResult(
                    stage=self.name,
                    out_dir=cache_dir,
                    command="(cached)",
                    exit_code=0,
                    cached=True,
                    cache_key=cache_key,
                )
            # Cache miss → use the cache_dir as out_dir so a successful run
            # populates it in-place; subsequent identical calls hit.
            out_dir = cache_dir
        else:
            run_id = _next_run_id()
            out_dir = workspace / f"{self.name}_{run_id:04d}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Inject out_dir as a keyword if the function accepts it
        sig = inspect.signature(self.func)
        if "out_dir" in sig.parameters:
            kwargs = {**kwargs, "out_dir": out_dir}

        command = self.func(*args, **kwargs)
        if not isinstance(command, str):
            raise TypeError(
                f"@stage function {self.func.__name__!r} must return a "
                f"shell command string; got {type(command).__name__}"
            )

        # External inputs (files / dirs outside the workspace) need their
        # own bind mounts and path rewrites — the workspace translator
        # below only touches paths under the workspace.
        ext_mounts, ext_translation = _collect_external_mounts(
            args, kwargs, workspace,
        )
        command = _apply_external_translation(command, ext_translation)
        translated = _translate_command(command, workspace)

        backend = _get_backend()

        # Version-gated DB refresh for annotation tools: check each DB's version
        # first and auto-update only the stale ones before the container runs.
        # Opt-in via $BIOFLOW_REFS (no-op otherwise); best-effort, never fatal.
        try:
            from bioflow.core.db import ensure_dbs_for_image  # noqa: PLC0415
            ensure_dbs_for_image(self.image)
        except Exception:  # pragma: no cover - defensive
            pass

        max_attempts = 1 + max(0, int(self.retry))

        # Resource bumping per attempt — each retry can multiply or
        # override cpu / ram_gb according to retry_with.
        cur_cpu = self.cpu
        cur_ram = self.ram_gb
        result: Optional[CommandResult] = None

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                cur_cpu, cur_ram = _bump_resources(
                    cur_cpu, cur_ram, self.retry_with,
                )
                log.warning(
                    f"RETRY stage={self.name}  attempt={attempt}/{max_attempts}"
                    f"  cpu={cur_cpu}  ram_gb={cur_ram}"
                )

            log.info(
                f"RUN  stage={self.name}  image={self.image}  "
                f"out_dir={out_dir.name}"
                + (f"  key={cache_key[:8]}" if cache_active else "")
                + (f"  attempt={attempt}/{max_attempts}" if max_attempts > 1 else "")
            )
            mounts = {str(workspace): str(_CONTAINER_WORKSPACE)}
            mounts.update(ext_mounts)
            run_kw: dict[str, Any] = dict(
                image=self.image,
                command=translated,
                mounts=mounts,
                cpu=cur_cpu,
                ram_gb=cur_ram,
                workdir=str(_CONTAINER_WORKSPACE),
                gpu=self.gpu,
            )
            # Only pass log_callback when (a) the backend supports
            # streaming (DockerBackend sets _STREAMING_SUPPORTED=True;
            # MockBackend doesn't accept kwargs it doesn't know about)
            # AND (b) the user opted in.
            # A staging backend needs to know which directories to ship out and
            # bring back.  Only backends that opt in are passed it, so the ones
            # with fixed signatures (Docker, Apptainer) stay untouched.
            if getattr(backend, "_WANTS_STAGE_IO", False):
                run_kw["stage_io"] = {
                    "out_dir": str(out_dir),
                    "inputs": _input_dirs(args, kwargs),
                }
            if (
                is_log_streaming_enabled()
                and getattr(backend, "_STREAMING_SUPPORTED", False)
            ):
                _stage_name = self.name
                run_kw["log_callback"] = lambda line, _s=_stage_name: log.info(
                    f"  [{_s}] {line}"
                )
            result = backend.run(**run_kw)
            if result.exit_code == 0:
                break

        assert result is not None
        sr = StageResult(
            stage=self.name,
            out_dir=out_dir,
            command=translated,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            cached=False,
            cache_key=cache_key,
        )
        _prov.record_stage(
            name=self.name, image=self.image, command=translated,
            exit_code=result.exit_code, cached=False, out_dir=out_dir,
            started_at=started_at, ended_at=_prov._now_iso(),
            args=args, kwargs=kwargs, backend=backend,
        )
        if sr.ok:
            log.info(f"DONE stage={self.name}  out_dir={out_dir.name}")
            # Mark cache complete only on success — failures must retry
            if cache_active and cache_dir is not None:
                try:
                    (cache_dir / CACHE_SENTINEL).touch()
                except OSError as exc:
                    log.warning(f"Could not write cache sentinel: {exc}")
        else:
            log.error(
                f"FAIL stage={self.name} exit={result.exit_code}  "
                f"out_dir={out_dir.name}"
                + (f"  exhausted {max_attempts} attempts" if max_attempts > 1 else "")
                + f"\n{(result.stderr or result.stdout)[-1000:]}"
            )
        return sr

    # ------------------------------------------------------------------
    # Fan-out execution
    # ------------------------------------------------------------------
    def map(
        self,
        inputs: Iterable[Any],
        *,
        parallel: Union[int, str] = 1,
        stop_on_error: bool = False,
        progress: Union[bool, _ProgressCallback] = False,
    ) -> list[StageResult]:
        """Run the stage once per element of *inputs*.

        Each element is passed as the **first positional argument** to the
        wrapped function.

        Parameters
        ----------
        inputs :
            Iterable of values; each becomes the sole positional arg per call.
        parallel :
            ``int`` — run N containers concurrently (1 = serial).
            ``"auto"`` — choose ``host_cpu // stage.cpu`` so the host is
            filled without oversubscription.
        stop_on_error :
            If True, the first failed run raises ``RuntimeError`` and
            outstanding work is cancelled.  Default keeps the batch going
            and returns the full result list (failures included).
        progress :
            ``True`` — show a single-line ANSI progress bar on stderr.
            ``False`` (default) — silent.
            *callable* — a custom hook ``cb(done, total, last_result)``.
        """
        sched = active_scheduler()
        if sched is not None:
            # Concurrent pipeline: submit each item to the shared scheduler so
            # the fan-out interleaves across stages (a fast item's downstream
            # can start while a slow sibling is still running) instead of
            # blocking on its own pool.  submit_call resolves future inputs and
            # honors depends_on per item.
            return cast("list[StageResult]", [
                sched.submit_call(self, self._run_once, (item,), {})
                for item in inputs
            ])
        return self._fanout(
            ((item,), {}) for item in inputs
        ).run(
            parallel=parallel,
            stop_on_error=stop_on_error,
            progress=progress,
            label=f"map[{self.name}]",
            return_iterator=False,
        )

    def starmap(
        self,
        inputs: Iterable[tuple],
        *,
        parallel: Union[int, str] = 1,
        stop_on_error: bool = False,
        progress: Union[bool, _ProgressCallback] = False,
    ) -> list[StageResult]:
        """Like :meth:`map` but each element of *inputs* is unpacked as
        positional args (or a ``(args, kwargs)`` 2-tuple for full control).

        Examples
        --------
        Two positional args::

            stage.starmap([(genome, ref), (g2, ref), (g3, ref)], parallel="auto")

        Mixed positional + keyword::

            stage.starmap([
                ((g1,), {"reference": ref, "min_qual": 30}),
                ((g2,), {"reference": ref, "min_qual": 30}),
            ], parallel=4)
        """
        items = list(inputs)
        normalised = []
        for it in items:
            if (
                isinstance(it, tuple) and len(it) == 2
                and isinstance(it[0], tuple) and isinstance(it[1], dict)
            ):
                normalised.append((it[0], it[1]))
            else:
                normalised.append((tuple(it), {}))
        sched = active_scheduler()
        if sched is not None:
            # Concurrent pipeline: one scheduled task per item, so the fan-out
            # interleaves across stages instead of blocking on its own pool.
            return cast("list[StageResult]", [
                sched.submit_call(self, self._run_once, a, k)
                for (a, k) in normalised
            ])
        return self._fanout(iter(normalised)).run(
            parallel=parallel,
            stop_on_error=stop_on_error,
            progress=progress,
            label=f"starmap[{self.name}]",
            return_iterator=False,
        )

    def imap_unordered(
        self,
        inputs: Iterable[Any],
        *,
        parallel: Union[int, str] = 1,
        progress: Union[bool, _ProgressCallback] = False,
    ) -> Iterator[StageResult]:
        """Yield :class:`StageResult` as each call completes (any order).

        Useful for streaming long batches where you want to start consuming
        outputs before all containers finish.  Caller cannot rely on input
        order — pair the result with ``sr.cache_key`` or your own key if
        ordering matters.
        """
        return self._fanout(
            ((item,), {}) for item in inputs
        ).run(
            parallel=parallel,
            stop_on_error=False,
            progress=progress,
            label=f"imap[{self.name}]",
            return_iterator=True,
        )

    # ------------------------------------------------------------------
    # Internal helper — shared engine for map / starmap / imap_unordered
    # ------------------------------------------------------------------
    def _fanout(self, plan_iter):
        return _FanoutPlan(self, list(plan_iter))


# ---------------------------------------------------------------------------
# Fan-out execution engine
# ---------------------------------------------------------------------------

class _FanoutPlan:
    """Internal — runs a list of (args, kwargs) tuples through one Stage.

    Centralises parallel-resolution, progress reporting, error semantics,
    and the serial-vs-parallel branch so map / starmap / imap_unordered
    don't duplicate logic.
    """

    def __init__(self, stage_obj: "Stage", plan: list[tuple[tuple, dict]]):
        self.stage = stage_obj
        self.plan = plan

    def run(
        self,
        *,
        parallel: Union[int, str],
        stop_on_error: bool,
        progress: Union[bool, _ProgressCallback],
        label: str,
        return_iterator: bool,
    ):
        n = len(self.plan)
        if n == 0:
            return iter([]) if return_iterator else []

        workers = _resolve_parallel(parallel, self.stage.cpu)
        log.info(
            f"FAN-OUT  stage={self.stage.name}  n={n}  parallel={workers}"
            + (" (auto)" if isinstance(parallel, str) else "")
        )

        # Resolve progress reporter
        if progress is True:
            progress_cb: Optional[_ProgressCallback] = _AnsiProgress(label, n)
        elif callable(progress):
            progress_cb = progress
        else:
            progress_cb = None

        def _one(i: int) -> tuple[int, StageResult]:
            args, kwargs = self.plan[i]
            return i, self.stage._run_once(args, kwargs)

        if return_iterator:
            return self._iter(workers, _one, progress_cb)

        results: list[Optional[StageResult]] = [None] * n
        done = 0

        if workers == 1:
            for i in range(n):
                _, sr = _one(i)
                results[i] = sr
                done += 1
                if progress_cb:
                    progress_cb(done, n, sr)
                if stop_on_error and not sr.ok:
                    raise RuntimeError(
                        f"Stage {self.stage.name!r} failed on input "
                        f"#{i} ({self.plan[i][0]!r}); see {sr.out_dir}"
                    )
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_one, i): i for i in range(n)}
                try:
                    for fut in as_completed(futs):
                        i, sr = fut.result()
                        results[i] = sr
                        done += 1
                        if progress_cb:
                            progress_cb(done, n, sr)
                        if stop_on_error and not sr.ok:
                            for f in futs:
                                f.cancel()
                            raise RuntimeError(
                                f"Stage {self.stage.name!r} failed on item "
                                f"{i}; see {sr.out_dir}"
                            )
                except KeyboardInterrupt:
                    log.warning("KeyboardInterrupt: cancelling pending tasks")
                    for f in futs:
                        f.cancel()
                    raise

        return [r for r in results if r is not None]

    def _iter(self, workers, _one, progress_cb):
        n = len(self.plan)
        done = 0
        if workers == 1:
            for i in range(n):
                _, sr = _one(i)
                done += 1
                if progress_cb:
                    progress_cb(done, n, sr)
                yield sr
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_one, i) for i in range(n)]
                for fut in as_completed(futs):
                    _, sr = fut.result()
                    done += 1
                    if progress_cb:
                        progress_cb(done, n, sr)
                    yield sr


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def stage(
    *,
    image: str,
    cpu: int = 2,
    ram_gb: float = 4.0,
    gpu: bool = False,
    description: str = "",
    cache: bool = True,
    depends_on: Optional[Union["Stage", Iterable["Stage"]]] = None,
    retry: int = 0,
    retry_with: Optional[dict] = None,
) -> Callable[[Callable[..., str]], Stage]:
    """Decorator: wrap a command-builder function into a :class:`Stage`.

    The decorated function must return a **shell command string** that
    will be executed inside *image*.  It receives the user's call
    arguments plus an injected keyword ``out_dir`` (a host ``Path`` to
    a fresh per-call directory inside the active workspace).

    Parameters
    ----------
    image, cpu, ram_gb, description :
        Container metadata.
    cache :
        When ``True`` (default), identical calls reuse a prior successful
        out_dir.  Cache key = image + cpu + ram_gb + builder source +
        every argument's content hash.  Set ``cache=False`` per stage to
        force re-execution every time (e.g. for stages with side effects
        such as network downloads with rate limits).
    depends_on :
        One Stage or an iterable of Stages whose outputs this stage
        consumes.  Pure metadata — bioflow does not auto-wire arguments;
        the user threads results explicitly inside a ``@pipeline``
        function.  Used by ``Pipeline.show_graph()`` /
        ``Pipeline.dry_run()`` for DAG visualisation, and as a sanity
        guard against typos that would otherwise only surface at runtime.

    Example
    -------
    >>> @stage(image="staphb/prokka:1.14.6", cpu=2, ram_gb=4)
    ... def annotate(genome_fna, *, out_dir):
    ...     return f"prokka --outdir {out_dir} {genome_fna}"
    """

    def decorator(func: Callable[..., str]) -> Stage:
        # Normalise depends_on → tuple[Stage, ...]
        if depends_on is None:
            deps: tuple = ()
        elif isinstance(depends_on, Stage):
            deps = (depends_on,)
        else:
            deps = tuple(depends_on)
            for d in deps:
                if not isinstance(d, Stage):
                    raise TypeError(
                        f"depends_on must contain Stage objects; got "
                        f"{type(d).__name__}"
                    )
        s = Stage(
            name=func.__name__,
            func=func,
            image=image,
            cpu=cpu,
            ram_gb=ram_gb,
            gpu=bool(gpu),
            description=description or (func.__doc__ or "").strip().split("\n")[0],
            cache=cache,
            depends_on=deps,
            retry=int(retry),
            retry_with=dict(retry_with or {}),
        )
        # Make the Stage object look reasonably like the original function
        functools.update_wrapper(s, func, updated=())
        return s

    return decorator
