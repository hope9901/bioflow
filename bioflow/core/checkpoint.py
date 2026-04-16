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
    save(workdir, state)
