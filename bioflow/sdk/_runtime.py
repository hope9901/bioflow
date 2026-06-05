"""Process-wide runtime state — active workspace + container backend.

These globals are intentionally shared across the SDK so end users never
have to thread `Workspace` / `Backend` objects through every recipe.  All
mutation goes through ``set_workspace`` / ``set_backend`` and is
serialised by a single lock.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from bioflow.core.logger import get_logger
from bioflow.core.runner import ContainerBackend, DockerBackend

log = get_logger()

_workspace_lock = threading.Lock()
_active_workspace: Optional[Path] = None
_active_backend: Optional[ContainerBackend] = None
_run_counter = 0


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
