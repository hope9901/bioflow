"""Cross-platform compatibility tests.

Covers:
* hardware.py  — arch normalisation (Windows AMD64, Linux aarch64, Apple Silicon arm64)
* compatibility.py — arm64 host + x86_64-only tool → runnable_slow, not incompatible
"""

from __future__ import annotations

from unittest.mock import patch


from bioflow.core.hardware import _ARCH_ALIASES, detect
from bioflow.core.compatibility import _arch_status, _status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(arch: list[str], min_cpu: int = 1, min_ram: float = 1.0,
               rec_cpu: int = 4, rec_ram: float = 8.0, gpu: bool = False):
    """Build a minimal Tool-like object for compatibility tests.

    Registry model layout:
      ResourceSpec  — top-level container with .min / .recommended / .arch / .gpu
      Resources     — leaf with .cpu / .ram_gb / .disk_gb
    """
    from bioflow.core.registry import (
        Applicable, ContainerSpec, ResourceSpec, Resources, Tool,
    )
    return Tool(
        id="test_tool",
        name="Test Tool",
        version="1.0",
        category="assembly",
        stage=["genome_assembly.step2"],
        input_types=["short_paired"],
        output_types=["assembly_fasta"],
        applicable=Applicable(species=[], read_type=[], mode=[]),
        container=ContainerSpec(image="example/tool:1.0", pull_policy="if_not_present"),
        resources=ResourceSpec(
            min=Resources(cpu=min_cpu, ram_gb=min_ram, disk_gb=0),
            recommended=Resources(cpu=rec_cpu, ram_gb=rec_ram, disk_gb=0),
            gpu=gpu,
            arch=arch,
        ),
        command_template="tool -i {r1} -o {out_dir}",
        references=[],
        citation="",
        added="2026-04-17",
        last_reviewed="2026-04-17",
    )


def _make_hw(arch: str, cpu: int = 16, ram: float = 32.0, gpu: bool = False):
    from bioflow.core.hardware import HardwareProfile
    return HardwareProfile(
        cpu_count=cpu,
        ram_gb=ram,
        disk_free_gb=500.0,
        arch=arch,
        os="linux",
        gpu_present=gpu,
    )


# ---------------------------------------------------------------------------
# Issue 1 — arch normalisation in hardware.py
# ---------------------------------------------------------------------------

class TestArchNormalisation:
    """_ARCH_ALIASES must map raw platform.machine() values to canonical tokens."""

    def test_amd64_maps_to_x86_64(self):
        assert _ARCH_ALIASES["amd64"] == "x86_64"

    def test_x86_64_unchanged(self):
        assert _ARCH_ALIASES["x86_64"] == "x86_64"

    def test_aarch64_maps_to_arm64(self):
        assert _ARCH_ALIASES["aarch64"] == "arm64"

    def test_arm64_unchanged(self):
        assert _ARCH_ALIASES["arm64"] == "arm64"

    def test_detect_normalises_windows_amd64(self, tmp_path):
        """detect() should store 'x86_64', not 'amd64', on a Windows-like host."""
        with patch("platform.machine", return_value="AMD64"):
            profile = detect(tmp_path)
        assert profile.arch == "x86_64"

    def test_detect_normalises_linux_aarch64(self, tmp_path):
        """detect() should store 'arm64', not 'aarch64', on Linux ARM hosts."""
        with patch("platform.machine", return_value="aarch64"):
            profile = detect(tmp_path)
        assert profile.arch == "arm64"

    def test_detect_preserves_x86_64(self, tmp_path):
        with patch("platform.machine", return_value="x86_64"):
            profile = detect(tmp_path)
        assert profile.arch == "x86_64"

    def test_detect_preserves_arm64(self, tmp_path):
        with patch("platform.machine", return_value="arm64"):
            profile = detect(tmp_path)
        assert profile.arch == "arm64"

    def test_detect_unknown_arch_lowercased(self, tmp_path):
        """Unknown arch values pass through lowercased rather than crashing."""
        with patch("platform.machine", return_value="MIPS64"):
            profile = detect(tmp_path)
        assert profile.arch == "mips64"


# ---------------------------------------------------------------------------
# Issue 2 — arm64 host + x86_64-only tool → runnable_slow
# ---------------------------------------------------------------------------

class TestArm64Compatibility:
    """arm64/aarch64 hosts can run x86_64 Docker images via Rosetta 2 / QEMU."""

    def test_arm64_host_x86_only_tool_is_slow_not_incompatible(self):
        st = _arch_status(["x86_64"], "arm64")
        assert st == "runnable_slow"

    def test_aarch64_host_x86_only_tool_is_slow_not_incompatible(self):
        st = _arch_status(["x86_64"], "aarch64")
        assert st == "runnable_slow"

    def test_arm64_host_arm64_tool_is_installable(self):
        st = _arch_status(["arm64", "x86_64"], "arm64")
        assert st == "installable"

    def test_x86_64_host_x86_only_tool_is_installable(self):
        st = _arch_status(["x86_64"], "x86_64")
        assert st == "installable"

    def test_x86_64_host_arm64_only_tool_is_incompatible(self):
        # x86_64 cannot emulate arm64 in Docker
        st = _arch_status(["arm64"], "x86_64")
        assert st == "incompatible"

    def test_no_arch_restriction_is_installable(self):
        st = _arch_status([], "arm64")
        assert st == "installable"

    def test_full_status_arm64_host_x86_only_tool_good_resources(self):
        """_status() must return runnable_slow even when resources are ample."""
        tool = _make_tool(arch=["x86_64"], min_cpu=2, min_ram=4.0,
                          rec_cpu=4, rec_ram=8.0)
        hw = _make_hw(arch="arm64", cpu=32, ram=64.0)
        assert _status(tool, hw) == "runnable_slow"

    def test_full_status_arm64_host_x86_only_tool_low_resources(self):
        """Low resources + emulation → still runnable_slow (resources dominate)."""
        tool = _make_tool(arch=["x86_64"], min_cpu=2, min_ram=4.0,
                          rec_cpu=32, rec_ram=128.0)
        hw = _make_hw(arch="arm64", cpu=8, ram=16.0)
        assert _status(tool, hw) == "runnable_slow"

    def test_full_status_arm64_host_no_arch_restriction_good_resources(self):
        """Tool with no arch restriction + sufficient resources → installable."""
        tool = _make_tool(arch=[], min_cpu=2, min_ram=4.0,
                          rec_cpu=4, rec_ram=8.0)
        hw = _make_hw(arch="arm64", cpu=16, ram=32.0)
        assert _status(tool, hw) == "installable"

    def test_full_status_x86_64_host_x86_only_tool_good_resources(self):
        """Normal x86_64 path unaffected."""
        tool = _make_tool(arch=["x86_64"], min_cpu=2, min_ram=4.0,
                          rec_cpu=4, rec_ram=8.0)
        hw = _make_hw(arch="x86_64", cpu=16, ram=32.0)
        assert _status(tool, hw) == "installable"


# ---------------------------------------------------------------------------
# Regression — existing x86_64 classify() behaviour unchanged
# ---------------------------------------------------------------------------

class TestClassifyRegression:
    def test_incompatible_when_below_min_cpu(self):
        tool = _make_tool(arch=["x86_64"], min_cpu=32, min_ram=4.0)
        hw = _make_hw(arch="x86_64", cpu=4, ram=16.0)
        from bioflow.core.compatibility import classify
        result = classify([tool], hw)
        assert tool in result["incompatible"]

    def test_runnable_slow_when_below_rec_ram(self):
        tool = _make_tool(arch=["x86_64"], min_cpu=2, min_ram=4.0,
                          rec_cpu=2, rec_ram=128.0)
        hw = _make_hw(arch="x86_64", cpu=8, ram=16.0)
        from bioflow.core.compatibility import classify
        result = classify([tool], hw)
        assert tool in result["runnable_slow"]
