"""Drift-guard: every container image referenced by a recipe must have a
corresponding tool YAML in ``registry/tools/``.

This enforces the "registry is the single source of truth" design
invariant.  When a recipe needs a tool not yet registered (e.g. a new
upstream library), the contributor must add the YAML so it shows up in
``bioflow tools``, gets hardware-classified, and can be picked up by
``bioflow update auto`` for monthly refreshes.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = REPO_ROOT / "registry" / "tools"
RECIPES_DIR = REPO_ROOT / "bioflow" / "recipes"


def _registry_images() -> set[str]:
    imgs = set()
    for p in REGISTRY_DIR.rglob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        if "container" in d and "image" in d["container"]:
            imgs.add(d["container"]["image"])
    return imgs


def _recipe_image_usages() -> dict[str, list[str]]:
    """{ image_str: [recipe_file_path, ...] } from every @stage(image=...)."""
    usage: dict[str, list[str]] = {}
    pattern = re.compile(r'image\s*=\s*["\']([^"\']+)["\']')
    for p in RECIPES_DIR.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            usage.setdefault(m.group(1), []).append(str(p.relative_to(REPO_ROOT)))
    return usage


class TestRecipeRegistryAlignment:

    def test_every_recipe_image_has_registry_entry(self):
        """No recipe may invent its own image — every image must be in
        the registry so it shows up in ``bioflow tools``."""
        reg = _registry_images()
        usage = _recipe_image_usages()
        missing = {img: refs for img, refs in usage.items() if img not in reg}
        if missing:
            lines = [
                "The following images are used by recipes but missing "
                "from registry/tools/:"
            ]
            for img, refs in sorted(missing.items()):
                lines.append(f"\n  {img}")
                for r in refs:
                    lines.append(f"    used by: {r}")
            lines.append(
                "\nAdd a YAML for each missing image under "
                "registry/tools/<category>/."
            )
            pytest.fail("\n".join(lines))


class TestPipelineModulesPresent:
    """Every pipeline ID referenced by a preset must have a
    ``bioflow/pipelines/<pipeline>.py`` module that defines its
    canonical stage IDs."""

    def test_every_preset_pipeline_has_module(self):
        pipelines_dir = REPO_ROOT / "bioflow" / "pipelines"
        existing = {p.stem for p in pipelines_dir.glob("*.py")
                    if p.name != "__init__.py"}
        for preset in (REPO_ROOT / "registry" / "presets").glob("*.yaml"):
            d = yaml.safe_load(preset.read_text(encoding="utf-8"))
            pl = d.get("pipeline")
            assert pl in existing, (
                f"preset {preset.name} references pipeline '{pl}' but "
                f"bioflow/pipelines/{pl}.py does not exist. "
                f"Available: {sorted(existing)}"
            )
