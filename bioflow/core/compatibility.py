"""Hardware <-> tool compatibility classification and preset recommendation.

Architecture compatibility matrix
----------------------------------
* Exact match                  → no penalty
* arm64 host + x86_64-only tool → ``runnable_slow``
  Docker Desktop (macOS/Windows) and QEMU (Linux) can run x86_64 images on
  arm64 hosts via emulation/Rosetta, but with a performance cost.
* Any other arch mismatch      → ``incompatible``
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml

from bioflow.core.hardware import HardwareProfile
from bioflow.core.registry import Tool

Status = Literal["installable", "runnable_slow", "incompatible"]

# Architectures that can run x86_64 Docker images via emulation (Rosetta 2 /
# QEMU binfmt_misc).  Emulation works but incurs a performance penalty, so
# we classify such combinations as runnable_slow rather than incompatible.
_EMULATES_X86_64: frozenset[str] = frozenset({"arm64", "aarch64"})


def _arch_status(tool_arches: list[str], hw_arch: str) -> Status:
    """Return arch-level status for a (tool_arches, hw_arch) combination."""
    if not tool_arches:
        return "installable"                     # no restriction declared
    if hw_arch in tool_arches:
        return "installable"                     # exact match
    # arm64 / aarch64 host + x86_64-only tool → emulation possible
    if hw_arch in _EMULATES_X86_64 and "x86_64" in tool_arches:
        return "runnable_slow"
    return "incompatible"


def _status(tool: Tool, hw: HardwareProfile) -> Status:
    # Architecture
    arch_st = _arch_status(tool.resources.arch, hw.arch)
    if arch_st == "incompatible":
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
    # Propagate arch emulation penalty even when resources are fine
    if arch_st == "runnable_slow":
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


# ---------------------------------------------------------------------------
# Preset recommendation
# ---------------------------------------------------------------------------

def recommend_presets(
    tools: list[Tool],
    hw: HardwareProfile,
    pipeline: str,
    *,
    registry_dir: Path = Path("registry"),
) -> list[dict]:
    """Score every preset for *pipeline* against *hw* and return recommendations.

    Scoring
    -------
    Each preset starts at 100 points.

    * ``-50`` per tool that is **incompatible** (below minimum resources or
      wrong arch).  A preset with any incompatible tool is marked
      ``runnable=False``.
    * ``-10`` per tool that is **runnable_slow** (below recommended resources).

    The returned list is sorted descending by score.

    Returns
    -------
    list[dict]
        Each entry has keys:
        ``preset``, ``score``, ``runnable``, ``description``,
        ``applies_to``, ``incompatible_tools``, ``slow_tools``.
    """
    preset_dir = registry_dir / "presets"
    if not preset_dir.exists():
        return []

    classified = classify(tools, hw)
    slow_ids: set[str] = {t.id for t in classified["runnable_slow"]}
    bad_ids:  set[str] = {t.id for t in classified["incompatible"]}

    results: list[dict] = []

    for preset_path in sorted(preset_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if data.get("pipeline") != pipeline:
            continue

        stage_tool_ids: list[str] = [
            s["tool_id"]
            for s in data.get("stages", [])
            if not s.get("skip") and s.get("tool_id")
        ]

        incompatible = [t for t in stage_tool_ids if t in bad_ids]
        slow         = [t for t in stage_tool_ids if t in slow_ids]

        score = 100 - len(incompatible) * 50 - len(slow) * 10

        results.append({
            "preset":            data["id"],
            "score":             score,
            "runnable":          len(incompatible) == 0,
            "description":       data.get("description", "").strip().replace("\n", " "),
            "applies_to":        data.get("applies_to", {}),
            "incompatible_tools": incompatible,
            "slow_tools":        slow,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)
