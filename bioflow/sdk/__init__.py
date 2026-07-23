"""bioflow SDK — `@stage` / `@pipeline` decorators and runtime config.

Tier-A (developer) API for wrapping container calls into reusable
Python functions and composing them into runnable pipelines.  Tier-B
(researcher) end users never import this directly — they invoke
recipes via the CLI.

The implementation is intentionally split across small files under
``bioflow.sdk`` (``_runtime``, ``_cache``, ``_hashing``, ``_paths``,
``_parallel``, ``_result``, ``_stage``, ``_pipeline``); this
``__init__`` re-exports the public surface and a handful of private
helpers that the test suite relies on.

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
"""
from __future__ import annotations

# Container backends re-exported for tests + first-party users that
# previously imported them from bioflow.sdk.
from bioflow.core.runner import (
    CommandResult,
    DockerBackend,
    MockBackend,
    SingularityBackend,
    SlurmBackend,
    make_backend,
)
from bioflow.core.staging import (  # noqa: F401
    LocalDirStore,
    ObjectStore,
    StagingBackend,
)

# Cache + log-streaming toggles
from bioflow.sdk._cache import (  # noqa: F401
    CACHE_SENTINEL,
    _env_disables_cache,
    clear_cache,
    is_cache_enabled,
    is_log_streaming_enabled,
    set_cache_enabled,
    set_log_streaming,
)

# Hashing (private, used by tests)
from bioflow.sdk._hashing import (  # noqa: F401
    _compute_cache_key,
    _hash_input_value,
)

# Parallel helpers (private, used by tests)
from bioflow.sdk._parallel import (  # noqa: F401
    _AnsiProgress,
    _bump_resources,
    _resolve_parallel,
)

# Path translation (private, used by tests)
from bioflow.sdk._paths import (  # noqa: F401
    _apply_external_translation,
    _collect_external_mounts,
    _to_container_path,
    _translate_command,
)

# Pipeline composition
from bioflow.sdk._concurrent import gather  # noqa: F401
from bioflow.sdk._pipeline import Pipeline, pipeline  # noqa: F401

# StageResult + Stage
from bioflow.sdk._result import StageResult  # noqa: F401

# Runtime globals
from bioflow.sdk._runtime import (  # noqa: F401
    _get_backend,
    _get_workspace,
    _next_run_id,
    set_backend,
    set_param_overrides,
    set_workspace,
)
from bioflow.sdk._stage import Stage, stage  # noqa: F401


def container_path(path) -> str:
    """Container-side (/work-relative) path for a workspace file.

    Recipes that build a *list file* of input paths consumed by a tool
    (e.g. FastANI's ``--ql``) can't rely on the command-string path
    translator — it only rewrites paths in the command, not inside files.
    Such recipes should stage their inputs into the workspace and write
    this container path into the list so the tool (whose working dir is
    ``/work``) can open them.

    Raises ``ValueError`` if *path* is outside the active workspace.
    """
    from pathlib import Path  # noqa: PLC0415
    return _to_container_path(Path(path), _get_workspace())


def stage_input(path, subdir: str = "staged_inputs") -> str:
    """Copy an external file into the workspace and return its container path.

    The one-stop helper for recipes that feed a tool a *list file* of
    input paths.  External inputs are normally bind-mounted at
    ``/inputs/<n>`` only when they appear as command arguments — paths
    that live *inside a file* the tool reads are neither mounted nor
    translated.  ``stage_input`` copies the file under the active
    workspace (which is always mounted at ``/work``) and returns the
    container path to write into the list, so it works regardless of
    whether the caller's ``out_dir`` equals the workspace.
    """
    import shutil  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    src = Path(path)
    dest_dir = _get_workspace() / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return _to_container_path(dest, _get_workspace())


__all__ = [
    "container_path",
    "stage_input",
    # Public Stage API
    "stage",
    "Stage",
    "StageResult",
    # Public Pipeline API
    "pipeline",
    "Pipeline",
    "gather",
    # Workspace / backend
    "set_workspace",
    "set_backend",
    "set_param_overrides",
    # Cache controls
    "set_cache_enabled",
    "is_cache_enabled",
    "clear_cache",
    "CACHE_SENTINEL",
    # Log streaming
    "set_log_streaming",
    "is_log_streaming_enabled",
    # Backends
    "MockBackend",
    "DockerBackend",
    "SingularityBackend",
    "SlurmBackend",
    "StagingBackend",
    "LocalDirStore",
    "ObjectStore",
    "make_backend",
    "CommandResult",
]
