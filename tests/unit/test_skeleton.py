"""Smoke tests for the skeleton — make sure every core module imports and
the CLI exposes the advertised subcommands."""

from __future__ import annotations

import importlib

import pytest


def test_package_imports():
    importlib.import_module("bioflow")
    for mod in [
        "bioflow.core.hardware",
        "bioflow.core.registry",
        "bioflow.core.compatibility",
        "bioflow.core.planner",
        "bioflow.core.runner",
        "bioflow.core.dag",
        "bioflow.core.checkpoint",
        "bioflow.core.logger",
        "bioflow.core.report",
        "bioflow.pipelines.genome_assembly",
        "bioflow.pipelines.rnaseq_deg",
    ]:
        importlib.import_module(mod)


def test_cli_subcommands_present():
    typer = pytest.importorskip("typer")  # CLI needs typer installed
    from bioflow.cli import app

    names = {c.name for c in app.registered_commands}
    assert {"hw", "tools", "recommend", "custom", "run", "db", "update"} <= names
