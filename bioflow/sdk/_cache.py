"""Cache toggle + container-log streaming toggle.

The cache itself is content-addressed by :mod:`bioflow.sdk._hashing`; the
toggles here are operator-level kill switches consulted on every stage
call.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from bioflow.core.logger import get_logger

from bioflow.sdk._runtime import _get_workspace

log = get_logger()


CACHE_SENTINEL = ".bioflow_cache_ok"
"""Marker file written into a stage's out_dir on success.  Subsequent calls
with identical cache keys treat the directory as a cache hit iff this file
exists.  Failed runs leave it absent, so retries are automatic."""

_cache_enabled: bool = True   # default ON; opt-out via env or set_cache_enabled
_log_streaming_enabled: bool = False   # default OFF; very chatty


def _env_disables_cache() -> bool:
    """Operator-level kill switch — checked on every cache decision so
    setting/unsetting BIOFLOW_NO_CACHE works without re-importing the
    module (and without poisoning class identity in long-running tests)."""
    return os.environ.get("BIOFLOW_NO_CACHE", "").lower() in ("1", "true", "yes")


def set_cache_enabled(flag: bool) -> None:
    """Globally toggle the input-hash cache.  Default ON."""
    global _cache_enabled
    _cache_enabled = bool(flag)
    log.info(f"bioflow cache: {'enabled' if _cache_enabled else 'disabled'}")


def is_cache_enabled() -> bool:
    return _cache_enabled and not _env_disables_cache()


def set_log_streaming(flag: bool) -> None:
    """Toggle real-time container stdout/stderr streaming.

    When True, each running container's output is forwarded to the
    bioflow logger at INFO level, prefixed by ``[stage_name]``.  Useful
    for long-running stages where ``tail -f`` would otherwise be needed.

    Also enabled by setting env var ``BIOFLOW_STREAM_LOGS=1``.  Default
    is OFF because some tools (e.g. Roary, IQ-TREE) emit several MB of
    chatty output that drowns the log.
    """
    global _log_streaming_enabled
    _log_streaming_enabled = bool(flag)


def is_log_streaming_enabled() -> bool:
    if os.environ.get("BIOFLOW_STREAM_LOGS", "").lower() in ("1", "true", "yes"):
        return True
    return _log_streaming_enabled


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
