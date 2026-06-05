"""Shared CLI primitives — the typer ``app`` and rich ``console`` instances.

Imported by every command submodule under ``bioflow.cli``.  Kept tiny on
purpose so the heavy command modules can register their decorators
without dragging in unrelated state.
"""
from __future__ import annotations

import sys

import typer
from rich.console import Console

from bioflow.core.registry import default_registry_dir as _default_registry_dir

# ── Windows-safe console encoding ───────────────────────────────────────────
# On non-UTF-8 Windows shells (e.g. Korean cp949) Rich's ✓/✗/⚠ glyphs raise
# UnicodeEncodeError mid-print and abort the command.  Force stdout/stderr to
# UTF-8 when the interpreter supports it (Python ≥ 3.7) — this is a no-op on
# already-UTF-8 terminals and keeps non-Windows behaviour unchanged.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass

# Registry default: ./registry in CWD (dev) or the wheel-bundled copy
# (pip install).  Computed once at import so it shows up in --help.
REGISTRY_DEFAULT = _default_registry_dir()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="bioflow: genome assembly/annotation & RNA-seq DEG pipeline platform.",
)
# Rich Console: keep colour but degrade glyphs gracefully on legacy code pages
console = Console(emoji=False, legacy_windows=False)
