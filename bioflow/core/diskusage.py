"""What is eating the disk, and how to get it back.

bioflow accumulates three things locally: the workspace stage cache, provisioned
reference databases, and pulled container images.  Until now it could *check*
free space (``bioflow doctor``) and *provision* databases, but offered no way to
see the breakdown or reclaim anything — so filling a disk meant deleting
directories by hand and guessing which ones mattered.

Everything here is read-only except :func:`remove_db`, which is the one
deliberate delete.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bioflow.core.db import _DB_CATALOG, _db_top_dir, catalog_version
from bioflow.core.logger import get_logger

log = get_logger()


def human(n_bytes: float) -> str:
    """Human-readable size, e.g. ``4.7 GB``."""
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n_bytes) < step or unit == "TB":
            return f"{n_bytes:.1f} {unit}" if unit != "B" else f"{int(n_bytes)} B"
        n_bytes /= step
    return f"{n_bytes:.1f} TB"   # pragma: no cover - unreachable


def dir_size(path: Path) -> int:
    """Total bytes under *path* (0 if it doesn't exist).

    Symlinks are not followed, so a linked-in reference bundle is counted where
    it actually lives rather than twice.
    """
    path = Path(path)
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:      # vanished mid-walk, or permission denied
            continue
    return total


@dataclass
class Entry:
    """One reclaimable thing on disk."""
    name: str
    path: Path
    bytes: int
    detail: str = ""

    @property
    def size(self) -> str:
        return human(self.bytes)


def db_usage(refs_root: Path) -> "list[Entry]":
    """Installed reference databases under *refs_root*, largest first."""
    refs_root = Path(refs_root)
    seen: "dict[str, Entry]" = {}
    for key in _DB_CATALOG:
        try:
            top = _db_top_dir(key)
        except (KeyError, IndexError):
            continue
        path = refs_root / top
        if not path.exists() or top in seen:
            continue
        version = catalog_version(key) or "-"
        seen[top] = Entry(name=key, path=path, bytes=dir_size(path),
                          detail=f"v{version}")
    return sorted(seen.values(), key=lambda e: e.bytes, reverse=True)


def cache_usage(workspace: Path) -> "list[Entry]":
    """Per-stage cache directories under ``<workspace>/.cache``, largest first."""
    cache_root = Path(workspace) / ".cache"
    if not cache_root.is_dir():
        return []
    entries = [
        Entry(name=child.name, path=child, bytes=dir_size(child))
        for child in cache_root.iterdir() if child.is_dir()
    ]
    return sorted(entries, key=lambda e: e.bytes, reverse=True)


def free_space(path: Path) -> "tuple[int, int]":
    """``(free_bytes, total_bytes)`` for the filesystem holding *path*."""
    usage = shutil.disk_usage(Path(path))
    return usage.free, usage.total


def remove_db(name: str, refs_root: Path) -> "Optional[Entry]":
    """Delete a provisioned database. Returns what was freed, or None.

    The only destructive call in this module — callers are expected to confirm
    with the user first.  Re-provision with ``bioflow db provision <name>``.
    """
    if name not in _DB_CATALOG:
        raise KeyError(f"Unknown database '{name}'.")
    path = Path(refs_root) / _db_top_dir(name)
    if not path.exists():
        return None
    entry = Entry(name=name, path=path, bytes=dir_size(path))
    shutil.rmtree(path, ignore_errors=True)
    log.info(f"removed DB '{name}' ({entry.size}) from {path}")
    return entry
