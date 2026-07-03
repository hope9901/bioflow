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


def _referenced_globals_digest(func) -> str:
    """Digest of the module-level names a builder function splices in.

    ``inspect.getsource(func)`` captures only the function body, so a change to
    a module-level *constant or helper it references* — e.g. a command-template
    string held in ``_GENOME_PLOT_FILTER`` — would NOT bust the cache and a run
    could silently reuse a stale result.  Reproducibility beats cache hits, so
    we walk the function's referenced global names (and, transitively, those of
    any helper defined in the same module) and hash:

      * ``str`` / ``bytes`` / number / ``bool`` constants (spliced into the
        command), and
      * the source of same-module helper functions.

    Imports from other modules (``Path``, ``re`` …) and builtins are ignored —
    their behaviour is pinned by the dependency set, not the recipe.
    """
    seen: "set[str]" = set()
    parts: "list[str]" = []

    def _walk(fn) -> None:
        code = getattr(fn, "__code__", None)
        g = getattr(fn, "__globals__", {})
        mod = getattr(fn, "__module__", None)
        for name in sorted(set(getattr(code, "co_names", ()))):
            if name in seen or name not in g:
                continue
            val = g[name]
            if isinstance(val, (str, bytes, int, float, bool)):
                seen.add(name)
                parts.append(f"{name}={val!r}")
            elif callable(val) and getattr(val, "__module__", None) == mod:
                seen.add(name)
                try:
                    parts.append(f"{name}:{inspect.getsource(val)}")
                except (OSError, TypeError):
                    parts.append(f"{name}:{getattr(val, '__qualname__', name)}")
                _walk(val)   # helper may splice in its own module-level names

    _walk(func)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def _compute_cache_key(stage_obj, args: tuple, kwargs: dict) -> str:
    """Deterministic 24-hex-char key from stage definition + inputs.

    A change in any of the following invalidates the cache:
      * container image
      * cpu / ram_gb (different resources may produce different output for
        non-deterministic tools)
      * source code of the command-builder function **and the module-level
        constants / helpers it references** (see
        :func:`_referenced_globals_digest`)
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
    parts.append(f"gsrc={_referenced_globals_digest(stage_obj.func)}")

    parts.extend(_hash_input_value(a) for a in args)
    for k in sorted(kwargs):
        if k == "out_dir":
            continue   # SDK-injected, varies per call by design
        parts.append(f"{k}={_hash_input_value(kwargs[k])}")

    full = "|".join(parts)
    return hashlib.sha256(full.encode()).hexdigest()[:24]
