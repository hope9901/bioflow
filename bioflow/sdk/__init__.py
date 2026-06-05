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
from bioflow.core.runner import CommandResult, DockerBackend, MockBackend

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
from bioflow.sdk._pipeline import Pipeline, pipeline  # noqa: F401

# StageResult + Stage
from bioflow.sdk._result import StageResult  # noqa: F401

# Runtime globals
from bioflow.sdk._runtime import (  # noqa: F401
    _get_backend,
    _get_workspace,
    _next_run_id,
    set_backend,
    set_workspace,
)
from bioflow.sdk._stage import Stage, stage  # noqa: F401

__all__ = [
    # Public Stage API
    "stage",
    "Stage",
    "StageResult",
    # Public Pipeline API
    "pipeline",
    "Pipeline",
    # Workspace / backend
    "set_workspace",
    "set_backend",
    # Cache controls
    "set_cache_enabled",
    "is_cache_enabled",
    "clear_cache",
    "CACHE_SENTINEL",
    # Log streaming
    "set_log_streaming",
    "is_log_streaming_enabled",
    # Backends (for tests)
    "MockBackend",
    "DockerBackend",
    "CommandResult",
]
