"""bioflow SDK — `@stage` decorator and recipe runner.

Tier-A (developer) API.  This is what bioflow maintainers use to wrap a
container call into a reusable Python function.  Tier-B (researcher)
end-users never import this directly — they invoke recipes via CLI.

Minimal example
---------------
::

    from bioflow.sdk import stage

    @stage(image="staphb/prokka:1.14.6", cpu=2, ram_gb=4)
    def annotate(genome_fna, *, out_dir):
        return (
            f"prokka --outdir {out_dir} --prefix {genome_fna.stem} "
            f"--kingdom Bacteria --cpus 2 {genome_fna}"
        )

    # Single call — runs one container
    result = annotate(Path("genome.fna"))

    # Fan-out — list input, optionally parallel
    results = annotate.map(
        [Path("g1.fna"), Path("g2.fna"), Path("g3.fna")],
        parallel=4,
    )

Design notes
------------
* The decorated function returns a **shell command string** that will run
  inside the container.  It receives the user's positional / keyword
  arguments unchanged, plus a special keyword ``out_dir`` that the SDK
  injects (a per-call workspace directory).
* The SDK takes care of:
    - allocating ``out_dir`` (under the active workspace)
    - mounting the workspace into the container
    - normalising host paths in the command to container paths
    - running via :class:`bioflow.core.runner.DockerBackend` (or any
      injected backend that satisfies ``ContainerBackend``)
    - parallel fan-out with ``ThreadPoolExecutor``
* Phase 1A scope: deterministic, no caching, no DAG resolver yet.  Those
  arrive in Phase 1B / 1C.  This file purposefully stays small.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Optional, Union

from bioflow.core.logger import get_logger
from bioflow.core.runner import (
    CommandResult,
    ContainerBackend,
    DockerBackend,
    MockBackend,  # re-export so tests can use it without touching .core
)

log = get_logger()

__all__ = [
    "stage",
    "Stage",
    "StageResult",
    "set_workspace",
    "set_backend",
    "set_cache_enabled",
    "is_cache_enabled",
    "clear_cache",
    "MockBackend",          # for unit tests
]


# ---------------------------------------------------------------------------
# Workspace + backend (process-wide defaults — overridable per call)
# ---------------------------------------------------------------------------

_workspace_lock = threading.Lock()
_active_workspace: Optional[Path] = None
_active_backend: Optional[ContainerBackend] = None
_run_counter = 0
_cache_enabled: bool = True   # default ON; opt-out via env or set_cache_enabled

# Honour BIOFLOW_NO_CACHE=1 at import time (operator-level kill switch)
if os.environ.get("BIOFLOW_NO_CACHE", "").lower() in ("1", "true", "yes"):
    _cache_enabled = False


def set_workspace(path: Path) -> None:
    """Set the host directory that holds every stage's per-call ``out_dir``.

    The directory is created on demand.  All stage runs after this call
    will mount this directory at ``/work`` inside the container.
    """
    global _active_workspace
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    with _workspace_lock:
        _active_workspace = path
    log.info(f"bioflow workspace -> {path}")


def set_backend(backend: ContainerBackend) -> None:
    """Replace the container backend (default = DockerBackend)."""
    global _active_backend
    with _workspace_lock:
        _active_backend = backend


def _get_workspace() -> Path:
    if _active_workspace is None:
        # Default to ./bioflow_work in the current working directory
        ws = Path.cwd() / "bioflow_work"
        set_workspace(ws)
    return _active_workspace  # type: ignore[return-value]


def _get_backend() -> ContainerBackend:
    global _active_backend
    if _active_backend is None:
        with _workspace_lock:
            if _active_backend is None:
                _active_backend = DockerBackend()
    return _active_backend


def _next_run_id() -> int:
    global _run_counter
    with _workspace_lock:
        _run_counter += 1
        return _run_counter


# ---------------------------------------------------------------------------
# Cache controls
# ---------------------------------------------------------------------------

CACHE_SENTINEL = ".bioflow_cache_ok"
"""Marker file written into a stage's out_dir on success.  Subsequent calls
with identical cache keys treat the directory as a cache hit iff this file
exists.  Failed runs leave it absent, so retries are automatic."""


def set_cache_enabled(flag: bool) -> None:
    """Globally toggle the input-hash cache.  Default ON."""
    global _cache_enabled
    _cache_enabled = bool(flag)
    log.info(f"bioflow cache: {'enabled' if _cache_enabled else 'disabled'}")


def is_cache_enabled() -> bool:
    return _cache_enabled


def clear_cache(workspace: Optional[Path] = None) -> int:
    """Delete every `<workspace>/.cache/*` directory.  Returns count removed.

    Use sparingly — every cached stage must re-run after this.
    """
    import shutil
    ws = Path(workspace) if workspace else _get_workspace()
    cache_root = ws / ".cache"
    if not cache_root.exists():
        return 0
    n = 0
    for child in cache_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            n += 1
    log.info(f"clear_cache: removed {n} entries under {cache_root}")
    return n


# ---------------------------------------------------------------------------
# Auto-parallelism + progress reporting
# ---------------------------------------------------------------------------

def _resolve_parallel(parallel: Union[int, str], cpu_per_stage: int) -> int:
    """Translate ``parallel="auto"`` into a concrete worker count.

    ``parallel=N`` (int) is honoured as-is, clamped to ≥ 1.
    ``parallel="auto"`` returns ``max(1, host_cpu // cpu_per_stage)`` so
    the host's logical CPU count is filled without oversubscription.
    """
    if isinstance(parallel, str):
        if parallel.lower() != "auto":
            raise ValueError(
                f"parallel must be int or 'auto', got {parallel!r}"
            )
        host_cpu = os.cpu_count() or 1
        return max(1, host_cpu // max(1, cpu_per_stage))
    return max(1, int(parallel))


_ProgressCallback = Callable[[int, int, "StageResult"], None]


class _AnsiProgress:
    """Minimal in-place progress bar — no tqdm dependency.

    ``update(i, n, sr)`` paints
        [###----- ]  4/12  cached=1  fail=0  stage_name
    on a single TTY line.  Falls back to per-completion log lines on
    non-TTY (CI logs, redirected stdout).
    """

    BAR_WIDTH = 28

    def __init__(self, label: str, total: int) -> None:
        self.label = label
        self.total = total
        self.cached = 0
        self.failed = 0
        self.tty = sys.stderr.isatty()
        self.last = -1
        self._lock = threading.Lock()
        self._t0 = time.time()

    def __call__(self, done: int, total: int, sr: "StageResult") -> None:
        with self._lock:
            if sr.cached:
                self.cached += 1
            if not sr.ok:
                self.failed += 1
            elapsed = time.time() - self._t0
            rate = done / max(elapsed, 0.01)
            eta = (total - done) / max(rate, 1e-3)
            if self.tty:
                filled = int(self.BAR_WIDTH * done / max(total, 1))
                bar = "#" * filled + "-" * (self.BAR_WIDTH - filled)
                msg = (
                    f"\r  [{bar}] {done:>4d}/{total}  "
                    f"cached={self.cached}  fail={self.failed}  "
                    f"eta={eta:>4.0f}s  {self.label}"
                )
                sys.stderr.write(msg)
                sys.stderr.flush()
                if done == total:
                    sys.stderr.write("\n")
                    sys.stderr.flush()
            else:
                # Non-TTY: emit once every ~5% so logs aren't flooded
                pct = int(100 * done / max(total, 1))
                if pct // 5 != self.last // 5 or done == total:
                    self.last = pct
                    log.info(
                        f"{self.label}: {done}/{total} "
                        f"({pct}%)  cached={self.cached}  fail={self.failed}"
                    )


# ---------------------------------------------------------------------------
# Cache key computation
# ---------------------------------------------------------------------------

def _hash_input_value(v: Any, _depth: int = 0) -> str:
    """Stable hash for a single Python value used as a stage input.

    Path objects: hashes (mtime_ns + size + first 64 KB content). This lets
    cheap mtime/size checks avoid full-content reads for unchanged files,
    while still detecting in-place edits.

    list / tuple / dict are hashed recursively.  Everything else falls back
    to repr() — good enough for ints, strings, simple dataclasses.
    """
    if _depth > 20:
        return "deep"   # guard against pathological nesting

    if isinstance(v, Path):
        try:
            st = v.stat()
        except (OSError, FileNotFoundError):
            return f"pathmissing:{hashlib.sha256(str(v).encode()).hexdigest()[:16]}"
        h = hashlib.sha256()
        h.update(str(st.st_mtime_ns).encode())
        h.update(b"|")
        h.update(str(st.st_size).encode())
        h.update(b"|")
        # Sample first 64 KB only — full file SHA is wasteful for multi-GB
        # genomes when mtime+size already discriminates.
        try:
            with v.open("rb") as fh:
                h.update(fh.read(65536))
        except (OSError, PermissionError):
            pass
        return f"file:{h.hexdigest()[:16]}"

    if isinstance(v, (list, tuple)):
        joined = ",".join(_hash_input_value(x, _depth + 1) for x in v)
        return f"seq:{hashlib.sha256(joined.encode()).hexdigest()[:16]}"

    if isinstance(v, dict):
        items = sorted(
            (str(k), _hash_input_value(val, _depth + 1)) for k, val in v.items()
        )
        joined = ";".join(f"{k}={h}" for k, h in items)
        return f"map:{hashlib.sha256(joined.encode()).hexdigest()[:16]}"

    # Fall through: repr() based — covers int, str, float, None, bool, dataclass
    return f"val:{hashlib.sha256(repr(v).encode()).hexdigest()[:16]}"


def _compute_cache_key(stage_obj: "Stage", args: tuple, kwargs: dict) -> str:
    """Deterministic 24-hex-char key from stage definition + inputs.

    A change in any of the following invalidates the cache:
      * container image
      * cpu / ram_gb (different resources may produce different output for
        non-deterministic tools)
      * source code of the command-builder function
      * any positional argument's hash (Path content / mtime / size, or repr)
      * any keyword argument's hash (out_dir is excluded — it's SDK-injected)
    """
    parts: list[str] = [
        f"image={stage_obj.image}",
        f"cpu={stage_obj.cpu}",
        f"ram_gb={stage_obj.ram_gb}",
    ]
    try:
        src = inspect.getsource(stage_obj.func)
    except (OSError, TypeError):
        src = stage_obj.func.__qualname__   # fallback for lambdas / built-ins
    parts.append(f"src={hashlib.sha256(src.encode()).hexdigest()[:16]}")

    parts.extend(_hash_input_value(a) for a in args)
    for k in sorted(kwargs):
        if k == "out_dir":
            continue   # SDK-injected, varies per call by design
        parts.append(f"{k}={_hash_input_value(kwargs[k])}")

    full = "|".join(parts)
    return hashlib.sha256(full.encode()).hexdigest()[:24]


# ---------------------------------------------------------------------------
# StageResult and Stage
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    """Returned by every stage call.  ``out_dir`` is the absolute host path
    that the stage's command was told to write into; downstream stages
    pass it (or files inside it) as inputs."""
    stage: str
    out_dir: Path
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    cached: bool = False
    cache_key: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


# ---------------------------------------------------------------------------
# Path translation: host <-> container
# ---------------------------------------------------------------------------

_CONTAINER_WORKSPACE = PurePosixPath("/work")


def _to_container_path(host_path: Path, workspace: Path) -> str:
    """Translate a host path inside the workspace to its /work-relative
    container path.  Raises if the host path is outside the workspace."""
    host_resolved = Path(host_path).resolve()
    try:
        rel = host_resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"Path {host_path!r} is outside the active workspace "
            f"{workspace!r}; stage commands can only reference files in the "
            f"mounted workspace."
        ) from exc
    return str(_CONTAINER_WORKSPACE / rel).replace("\\", "/")


def _translate_command(command: str, workspace: Path) -> str:
    """Replace any literal occurrences of the host workspace path in *command*
    with the container path.  This lets users write commands using regular
    pathlib.Path objects without manually computing /work/... strings.

    Windows: the host workspace contains backslashes ("C:\\Users\\...\\ws").
    After substituting the workspace prefix with "/work", any path component
    *after* the prefix (e.g. "\\data.fna") would still hold backslashes.
    A second pass normalises those tail components to forward slashes so the
    command is a valid POSIX path inside the container.
    """
    import re

    ws_str = str(workspace)
    container = str(_CONTAINER_WORKSPACE)
    # Both forward- and back-slashed forms (Windows users)
    out = command.replace(ws_str, container).replace(
        ws_str.replace("\\", "/"), container,
    )
    # Normalise backslashes that follow the /work prefix
    return re.sub(
        r"(/work)([\\/][^\s'\"<>|;&]*)",
        lambda m: m.group(1) + m.group(2).replace("\\", "/"),
        out,
    )


# ---------------------------------------------------------------------------
# Stage object
# ---------------------------------------------------------------------------

@dataclass
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
    description: str = ""
    cache: bool = True

    # ------------------------------------------------------------------
    # Single-call execution
    # ------------------------------------------------------------------
    def __call__(self, *args: Any, **kwargs: Any) -> StageResult:
        return self._run_once(args, kwargs)

    def _run_once(self, args: tuple, kwargs: dict) -> StageResult:
        workspace = _get_workspace()

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

        translated = _translate_command(command, workspace)
        log.info(
            f"RUN  stage={self.name}  image={self.image}  "
            f"out_dir={out_dir.name}"
            + (f"  key={cache_key[:8]}" if cache_active else "")
        )

        backend = _get_backend()
        run_kwargs = dict(
            image=self.image,
            command=translated,
            mounts={str(workspace): str(_CONTAINER_WORKSPACE)},
            cpu=self.cpu,
            ram_gb=self.ram_gb,
            workdir=str(_CONTAINER_WORKSPACE),
        )
        result: CommandResult = backend.run(**run_kwargs)

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
                f"out_dir={out_dir.name}\n{(result.stderr or result.stdout)[-1000:]}"
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
    description: str = "",
    cache: bool = True,
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

    Example
    -------
    >>> @stage(image="staphb/prokka:1.14.6", cpu=2, ram_gb=4)
    ... def annotate(genome_fna, *, out_dir):
    ...     return f"prokka --outdir {out_dir} {genome_fna}"
    """

    def decorator(func: Callable[..., str]) -> Stage:
        s = Stage(
            name=func.__name__,
            func=func,
            image=image,
            cpu=cpu,
            ram_gb=ram_gb,
            description=description or (func.__doc__ or "").strip().split("\n")[0],
            cache=cache,
        )
        # Make the Stage object look reasonably like the original function
        functools.update_wrapper(s, func, updated=())
        return s

    return decorator
