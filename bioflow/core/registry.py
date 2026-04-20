"""Tool Registry loader.

Reads `registry/tools/**/*.yaml`, validates each against `registry/schema.yaml`
(JSON Schema), and returns typed Tool objects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field


class Resources(BaseModel):
    cpu: int
    ram_gb: float
    disk_gb: float = 0


class ResourceSpec(BaseModel):
    min: Resources
    recommended: Resources
    gpu: bool = False
    arch: list[str] = Field(default_factory=lambda: ["x86_64"])


class ContainerSpec(BaseModel):
    image: str
    pull_policy: Literal["always", "if_not_present", "never"] = "if_not_present"


class Applicable(BaseModel):
    species: list[str] = Field(default_factory=list)       # prokaryote | eukaryote | eukaryote_small | any
    read_type: list[str] = Field(default_factory=list)     # short | long_hifi | long_ont | hybrid | any
    mode: list[str] = Field(default_factory=list)          # de_novo | resequencing | any


class Tool(BaseModel):
    id: str
    name: str
    version: str
    category: str
    stage: list[str]
    input_types: list[str] = Field(default_factory=list)
    output_types: list[str] = Field(default_factory=list)
    applicable: Applicable
    container: ContainerSpec
    resources: ResourceSpec
    command_template: str
    references: list[str] = Field(default_factory=list)
    citation: Optional[str] = None
    added: Optional[str] = None
    last_reviewed: Optional[str] = None


def _load_schema(registry_dir: Path) -> dict:
    schema_path = registry_dir / "schema.yaml"
    with schema_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_registry(registry_dir: Path) -> list[Tool]:
    """Load and validate every tool YAML under `registry_dir/tools/`."""
    schema = _load_schema(registry_dir)
    validator = Draft202012Validator(schema)
    tools: list[Tool] = []
    tools_root = registry_dir / "tools"
    if not tools_root.exists():
        return tools
    from bioflow.core.logger import get_logger  # noqa: PLC0415
    log = get_logger()
    for path in tools_root.rglob("*.yaml"):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            log.warning(f"Skipping unparseable YAML {path}: {exc}")
            continue
        if data is None or not isinstance(data, dict):
            log.warning(f"Skipping empty/non-mapping YAML {path}")
            continue
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        if errors:
            msgs = "\n  ".join(f"{list(e.path)}: {e.message}" for e in errors)
            log.warning(
                f"Skipping invalid tool registry file {path}:\n  {msgs}"
            )
            continue
        try:
            tools.append(Tool.model_validate(data))
        except Exception as exc:
            log.warning(f"Skipping {path}: Tool model validation failed: {exc}")
            continue
    return tools
