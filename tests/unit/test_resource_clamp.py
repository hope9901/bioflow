"""DockerBackend must clamp requested CPU/RAM to the host's capacity.

Regression test for the bug the full-pipeline e2e caught: a stage
declaring cpu=8 failed to even start on a 4-core CI runner because Docker
rejects --cpus above the host core count.
"""
from __future__ import annotations

import bioflow.core.runner as runner
from bioflow.core.runner import _clamp_resources


class TestClampResources:

    def test_cpu_clamped_to_host(self, monkeypatch):
        monkeypatch.setattr(runner.os, "cpu_count", lambda: 4)
        eff_cpu, _ = _clamp_resources(8, 4.0)
        assert eff_cpu == 4

    def test_cpu_not_inflated_when_under_host(self, monkeypatch):
        monkeypatch.setattr(runner.os, "cpu_count", lambda: 16)
        eff_cpu, _ = _clamp_resources(8, 4.0)
        assert eff_cpu == 8

    def test_cpu_floors_at_one(self, monkeypatch):
        monkeypatch.setattr(runner.os, "cpu_count", lambda: None)
        eff_cpu, _ = _clamp_resources(8, 4.0)
        assert eff_cpu == 1

    def test_ram_clamped_below_host(self, monkeypatch):
        monkeypatch.setattr(runner.os, "cpu_count", lambda: 8)

        import psutil

        class _Mem:
            total = int(16 * 1024 ** 3)   # 16 GB host

        monkeypatch.setattr(psutil, "virtual_memory", lambda: _Mem())
        # Stage asks for 64 GB → clamp to ~90% of 16 GB.
        _, eff_ram = _clamp_resources(8, 64.0)
        assert eff_ram <= 16.0
        assert eff_ram >= 14.0      # ~0.9 * 16

    def test_ram_unchanged_when_under_host(self, monkeypatch):
        monkeypatch.setattr(runner.os, "cpu_count", lambda: 8)

        import psutil

        class _Mem:
            total = int(64 * 1024 ** 3)

        monkeypatch.setattr(psutil, "virtual_memory", lambda: _Mem())
        _, eff_ram = _clamp_resources(8, 16.0)
        assert eff_ram == 16.0
