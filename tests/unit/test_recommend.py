"""Unit tests for compatibility.recommend_presets (item 6)."""
from __future__ import annotations

from pathlib import Path


REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


def _make_hw(cpu=32, ram=64.0, gpu=False, arch="x86_64", disk=500.0):
    from bioflow.core.hardware import HardwareProfile
    return HardwareProfile(
        cpu_count=cpu, ram_gb=ram, gpu_present=gpu,
        arch=arch, disk_free_gb=disk, docker_available=True,
        os="linux",
    )


def test_recommend_genome_assembly_returns_presets():
    from bioflow.core.compatibility import recommend_presets
    from bioflow.core.registry import load_registry

    tools = load_registry(REGISTRY_DIR)
    hw = _make_hw()
    recs = recommend_presets(tools, hw, "genome_assembly", registry_dir=REGISTRY_DIR)

    assert len(recs) > 0
    # All entries have required keys
    for r in recs:
        assert "preset" in r
        assert "score" in r
        assert "runnable" in r
        assert isinstance(r["incompatible_tools"], list)
        assert isinstance(r["slow_tools"], list)


def test_recommend_sorted_descending_by_score():
    from bioflow.core.compatibility import recommend_presets
    from bioflow.core.registry import load_registry

    tools = load_registry(REGISTRY_DIR)
    hw = _make_hw()
    recs = recommend_presets(tools, hw, "genome_assembly", registry_dir=REGISTRY_DIR)
    scores = [r["score"] for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_recommend_rnaseq_pipeline():
    from bioflow.core.compatibility import recommend_presets
    from bioflow.core.registry import load_registry

    tools = load_registry(REGISTRY_DIR)
    hw = _make_hw()
    recs = recommend_presets(tools, hw, "rnaseq_deg", registry_dir=REGISTRY_DIR)
    assert len(recs) > 0
    assert all(r["preset"].startswith("rnaseq") for r in recs)


def test_recommend_unknown_pipeline_returns_empty():
    from bioflow.core.compatibility import recommend_presets
    from bioflow.core.registry import load_registry

    tools = load_registry(REGISTRY_DIR)
    hw = _make_hw()
    recs = recommend_presets(tools, hw, "nonexistent_pipeline", registry_dir=REGISTRY_DIR)
    assert recs == []


def test_recommend_low_resource_host_marks_slow():
    """A host with 2 CPUs / 4 GB RAM should have many slow tools."""
    from bioflow.core.compatibility import recommend_presets
    from bioflow.core.registry import load_registry

    tools = load_registry(REGISTRY_DIR)
    hw = _make_hw(cpu=2, ram=4.0)
    recs = recommend_presets(tools, hw, "genome_assembly", registry_dir=REGISTRY_DIR)
    # At least some presets should have slow tools on a weak host
    has_slow = any(len(r["slow_tools"]) > 0 for r in recs)
    assert has_slow, "Expected some slow tools on a 2-CPU/4-GB host"


def test_recommend_best_preset_is_runnable_on_good_hw():
    """On a well-resourced host, the top preset should be runnable."""
    from bioflow.core.compatibility import recommend_presets
    from bioflow.core.registry import load_registry

    tools = load_registry(REGISTRY_DIR)
    hw = _make_hw(cpu=64, ram=256.0, disk=2000.0)
    recs = recommend_presets(tools, hw, "genome_assembly", registry_dir=REGISTRY_DIR)
    assert recs[0]["runnable"] is True
