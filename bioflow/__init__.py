"""bioflow - bioinformatics pipeline platform."""

__version__ = "0.1.0"

# Tier-A SDK (Phase 1A: @stage decorator)
from bioflow.sdk import (  # noqa: E402,F401
    stage,
    Stage,
    StageResult,
    pipeline,
    Pipeline,
    set_workspace,
    set_backend,
    set_cache_enabled,
    is_cache_enabled,
    clear_cache,
    set_log_streaming,
    is_log_streaming_enabled,
    MockBackend,
)
from bioflow.report import Report  # noqa: E402,F401
