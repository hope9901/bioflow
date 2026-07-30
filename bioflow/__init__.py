"""bioflow - bioinformatics pipeline platform."""

__version__ = "0.3.1"

# Tier-A SDK — @stage / @pipeline / runtime config
from bioflow.report import Report  # noqa: F401
from bioflow.sdk import (  # noqa: F401
    DockerBackend,
    MockBackend,
    Pipeline,
    Stage,
    StageResult,
    clear_cache,
    container_path,
    gather,
    is_cache_enabled,
    is_log_streaming_enabled,
    pipeline,
    set_backend,
    set_cache_enabled,
    set_log_streaming,
    set_workspace,
    stage,
    stage_input,
)
