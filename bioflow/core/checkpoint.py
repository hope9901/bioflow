"""Checkpoint / resume.

Persists per-stage state to `<workdir>/.bioflow_state.json` so `bioflow run`
can skip already-finished stages on retry.

Safety notes
------------
* ``save()`` writes to a temporary file then uses ``os.replace()`` (POSIX-atomic
  on Linux/macOS; atomic on Windows NTFS) so a mid-write crash never leaves a
  partially-written state file.
* ``load()`` recovers gracefully from a corrupted / truncated JSON file by
  resetting to an empty state and logging a warning.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from bioflow.core.logger import get_logger

log = get_logger()

STATE_FILE = ".bioflow_state.json"


def _empty() -> dict:
    return {"completed_stages": [], "artifacts": {}}


def load(workdir: Path) -> dict:
    p = workdir / STATE_FILE
    if not p.exists():
        return _empty()
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        # Ensure required keys exist even if the file was hand-edited
        state.setdefault("completed_stages", [])
        state.setdefault("artifacts", {})
        return state
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning(
            f"State file {p} is corrupted ({exc}) — resetting to empty state. "
            "Previously completed stages will be re-run."
        )
        return _empty()


def save(workdir: Path, state: dict) -> None:
    """Write *state* atomically via a temp-file + os.replace()."""
    target = workdir / STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write to a sibling temp file, then atomically rename
    fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp_path, str(target))
    except Exception:
        # Clean up temp file on any error
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def mark_completed(workdir: Path, stage_id: str, outputs: dict) -> None:
    state = load(workdir)
    if stage_id not in state["completed_stages"]:
        state["completed_stages"].append(stage_id)
    state["artifacts"][stage_id] = outputs
    # If it was previously recorded as failed, clear that entry
    state.get("failed_stages", {}).pop(stage_id, None)
    save(workdir, state)


def mark_failed(workdir: Path, stage_id: str, error: str, stderr: str = "") -> None:
    """Record a failed stage with error details for post-run reporting."""
    state = load(workdir)
    state.setdefault("failed_stages", {})[stage_id] = {
        "error": error,
        "stderr_tail": stderr[-2000:] if stderr else "",
    }
    save(workdir, state)
