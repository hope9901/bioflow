"""Checkpoint / resume.

Persists per-stage state to `<workdir>/.bioflow_state.json` so `bioflow run`
can skip already-finished stages on retry.
"""

from __future__ import annotations

import json
from pathlib import Path

STATE_FILE = ".bioflow_state.json"


def load(workdir: Path) -> dict:
    p = workdir / STATE_FILE
    if not p.exists():
        return {"completed_stages": [], "artifacts": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def save(workdir: Path, state: dict) -> None:
    (workdir / STATE_FILE).write_text(
        json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
    )


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
