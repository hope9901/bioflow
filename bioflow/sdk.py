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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Optional

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
        parallel: int = 1,
        stop_on_error: bool = False,
    ) -> list[StageResult]:
        """Run the stage once per element of *inputs*.

        Each element is passed as the **first positional argument** to the
        wrapped function.  Use ``parallel`` > 1 to run N containers
        concurrently via :class:`ThreadPoolExecutor`.

        Returns a list of :class:`StageResult` in the same order as
        *inputs*.  Failed runs are included (with ``exit_code != 0``) unless
        ``stop_on_error=True``, in which case the first failure raises
        ``RuntimeError`` and outstanding work is cancelled.
        """
        items = list(inputs)
        results: list[Optional[StageResult]] = [None] * len(items)

        def _one(i: int, item: Any) -> tuple[int, StageResult]:
            return i, self._run_once((item,), {})

        if parallel <= 1:
            for i, item in enumerate(items):
                _, results[i] = _one(i, item)
                if stop_on_error and results[i] and not results[i].ok:
                    raise RuntimeError(
                        f"Stage {self.name!r} failed on input {item!r}; "
                        f"see {results[i].out_dir}"
                    )
        else:
            log.info(
                f"MAP  stage={self.name}  n={len(items)}  parallel={parallel}"
            )
            with ThreadPoolExecutor(max_workers=parallel) as ex:
                futs = {
                    ex.submit(_one, i, item): i
                    for i, item in enumerate(items)
                }
                for fut in as_completed(futs):
                    i, sr = fut.result()
                    results[i] = sr
                    if stop_on_error and not sr.ok:
                        for f in futs:
                            f.cancel()
                        raise RuntimeError(
                            f"Stage {self.name!r} failed on input "
                            f"{items[i]!r}; see {sr.out_dir}"
                        )
        # All slots populated by now
        return [r for r in results if r is not None]


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
