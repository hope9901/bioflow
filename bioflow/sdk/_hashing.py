"""Stable content hashing for cache keys.

Decoupled from :class:`bioflow.sdk._stage.Stage` so its dependencies stay
small (no Stage-class import) — the hashing functions accept a
duck-typed ``stage_obj`` with ``image``, ``cpu``, ``ram_gb``, ``func``
attributes.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any


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

    # StageResult — hash by the cache-addressed out_dir path string only.
    # The directory name already encodes the upstream cache key, so two
    # successive runs of the same upstream produce StageResults that hash
    # identically here regardless of whether `command` is "(cached)" or
    # the real shell line.  Without this, a fresh-vs-cached upstream
    # would invalidate every downstream cache.
    if v.__class__.__name__ == "StageResult" and hasattr(v, "out_dir"):
        return f"sresult:{hashlib.sha256(str(v.out_dir).encode()).hexdigest()[:16]}"

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


def _compute_cache_key(stage_obj, args: tuple, kwargs: dict) -> str:
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
