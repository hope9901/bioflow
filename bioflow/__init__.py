"""bioflow - bioinformatics pipeline platform."""

__version__ = "0.1.0"

# Tier-A SDK (Phase 1A: @stage decorator)
from bioflow.sdk import (  # noqa: E402,F401
    stage,
    Stage,
    StageResult,
    set_workspace,
    set_backend,
    MockBackend,
)
