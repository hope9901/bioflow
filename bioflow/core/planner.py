"""Pipeline planner.

Builds an ExecutionPlan either from a preset YAML (recommend mode) or from
interactive user selection (custom mode), or from a previously saved config file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class StagePlan(BaseModel):
    stage_id: str           # e.g. "genome_assembly.step2"
    tool_id: str            # resolved tool id from registry
    params: dict = {}       # per-invocation overrides


class ExecutionPlan(BaseModel):
    pipeline: str                 # "genome_assembly" | "rnaseq_deg"
    preset: Optional[str] = None
    species: str
    read_type: str
    mode: str
    inputs: dict                  # paths to raw data, sample sheet, reference, etc.
    stages: list[StagePlan]
    workdir: Path
    registry_dir: Path = Path("registry")


def plan_from_preset(preset: str, config: Path) -> ExecutionPlan:
    """Load preset YAML + user config → ExecutionPlan."""
    raise NotImplementedError("Implement in step 8 (preset mode).")


def plan_from_config(config: Path) -> ExecutionPlan:
    """Load a saved full ExecutionPlan YAML."""
    with config.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ExecutionPlan.model_validate(data)


def interactive_build(pipeline: str, out: Path) -> None:
    """Interactive `bioflow custom` flow — implemented in step 8."""
    raise NotImplementedError("Implement in step 8 (custom mode).")
