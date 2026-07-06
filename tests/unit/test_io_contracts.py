"""The I/O-contract snapshot must stay in lockstep with the registry, and the
drift classifier must flag an I/O-changing version bump (the case that can
break a downstream recipe stage).

See scripts/io_contracts.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "io_contracts.py"


def _load():
    spec = importlib.util.spec_from_file_location("io_contracts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


IO = _load()


def test_snapshot_matches_registry():
    """registry/io_contracts.json is regenerated whenever a tool version or its
    input/output types change — the same freshness contract as docs-fresh.
    Run `python scripts/io_contracts.py update` and commit if this fails."""
    live = IO._load_live()
    snap = IO._load_snapshot()
    added, removed, io_drift, version_only, refresh = IO._diff(live, snap)
    assert not (added or removed or io_drift or version_only or refresh), (
        "io_contracts snapshot is stale: "
        f"added={added} removed={removed} io_drift={io_drift} "
        f"version_only={version_only} refresh={refresh}. "
        "Run `python scripts/io_contracts.py update` and commit."
    )


def test_every_tool_has_a_contract():
    """Every registered tool declares at least one input or output format, so a
    bump never lands with an empty (uncheckable) contract."""
    live = IO._load_live()
    empty = [tid for tid, v in live.items() if not v["inputs"] and not v["outputs"]]
    assert not empty, f"tools with no input_types/output_types: {empty}"


def test_diff_flags_io_changing_bump():
    """A version bump that also changes outputs is classified as io_drift (not a
    harmless version-only refresh)."""
    snap = {"toolx": {"version": "1.0", "inputs": ["fastq"], "outputs": ["bam"]}}
    live = {"toolx": {"version": "2.0", "image": "x:2.0",
                      "inputs": ["fastq"], "outputs": ["cram"]}}
    added, removed, io_drift, version_only, refresh = IO._diff(live, snap)
    assert io_drift == ["toolx"]
    assert version_only == [] and refresh == []


def test_diff_version_only_is_not_drift():
    """A pure build/version bump with an unchanged contract is version-only, not
    drift (safe to auto-adopt)."""
    snap = {"toolx": {"version": "1.0", "inputs": ["fastq"], "outputs": ["bam"]}}
    live = {"toolx": {"version": "1.1", "image": "x:1.1",
                      "inputs": ["fastq"], "outputs": ["bam"]}}
    _, _, io_drift, version_only, _ = IO._diff(live, snap)
    assert io_drift == [] and version_only == ["toolx"]


def test_affected_recipes_are_resolved():
    """Contract drift on a recipe-used tool must name the recipe file(s) that
    pin it, so the bump author knows what to re-verify."""
    live = IO._load_live()
    recipes = IO._tool_recipes(live)
    # fastp is used by several recipes; it must resolve to at least one file.
    assert recipes.get("fastp"), "fastp should map to recipe files"
    assert all(r.endswith(".py") for r in recipes["fastp"])
