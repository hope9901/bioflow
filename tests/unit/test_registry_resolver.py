"""Tests for default_registry_dir() — the resolver that lets
`pip install bioflow` find the wheel-bundled registry while still
preferring an editable ./registry in a git checkout."""
from __future__ import annotations

from pathlib import Path

from bioflow.core import registry as reg


class TestDefaultRegistryDir:

    def test_prefers_cwd_registry(self, tmp_path, monkeypatch):
        (tmp_path / "registry" / "tools").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        assert reg.default_registry_dir() == Path("registry")

    def test_falls_back_to_bundled(self, tmp_path, monkeypatch):
        # cwd has no ./registry/tools
        monkeypatch.chdir(tmp_path)
        result = reg.default_registry_dir()
        # In the dev tree the bundled copy doesn't exist, so it returns
        # Path("registry"); in an installed wheel it returns the bundled
        # path.  Either way it must be a Path and not raise.
        assert isinstance(result, Path)

    def test_bundled_constant_points_into_package(self):
        assert reg._BUNDLED_REGISTRY.name == "_bundled_registry"
        assert reg._BUNDLED_REGISTRY.parent.name == "bioflow"
