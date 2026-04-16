"""Hardware <-> tool compatibility classification."""

from __future__ import annotations

from typing import Literal, Optional

from bioflow.core.hardware import HardwareProfile
from bioflow.core.registry import Tool

Status = Literal["installable", "runnable_slow", "incompatible"]


def _status(tool: Tool, hw: HardwareProfile) -> Status:
    # Architecture
    if tool.resources.arch and hw.arch not in tool.resources.arch:
        return "incompatible"
    # GPU
    if tool.resources.gpu and not hw.gpu_present:
        return "incompatible"
    # Min resources
    if hw.cpu_count < tool.resources.min.cpu:
        return "incompatible"
    if hw.ram_gb < tool.resources.min.ram_gb:
        return "incompatible"
    if tool.resources.min.disk_gb and hw.disk_free_gb < tool.resources.min.disk_gb:
        return "incompatible"
    # Recommended resources → runnable but possibly slow
    rec = tool.resources.recommended
    if hw.cpu_count < rec.cpu or hw.ram_gb < rec.ram_gb:
        return "runnable_slow"
    return "installable"


def classify(tools: list[Tool], hw: HardwareProfile) -> dict[Status, list[Tool]]:
    """Bucket tools into installable / runnable_slow / incompatible."""
    buckets: dict[Status, list[Tool]] = {
        "installable": [],
        "runnable_slow": [],
        "incompatible": [],
    }
    for t in tools:
        buckets[_status(t, hw)].append(t)
    return buckets


def filter_applicable(
    tools: list[Tool],
    *,
    species: Optional[str] = None,
    read_type: Optional[str] = None,
    mode: Optional[str] = None,
    stage: Optional[str] = None,
) -> list[Tool]:
    """Filter tools by pipeline context (species/read/mode/stage)."""
    def match(allowed: list[str], value: Optional[str]) -> bool:
        if not allowed or "any" in allowed:
            return True
        return value is None or value in allowed

    out: list[Tool] = []
    for t in tools:
        if stage and stage not in t.stage:
            continue
        if not match(t.applicable.species, species):
            continue
        if not match(t.applicable.read_type, read_type):
            continue
        if not match(t.applicable.mode, mode):
            continue
        out.append(t)
    return out
