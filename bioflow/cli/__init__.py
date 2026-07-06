"""bioflow CLI entry point — typer app + per-command submodules.

The single ``app`` is defined in :mod:`bioflow.cli._app` and decorated by
every command module imported below.  Importing this package is therefore
the trigger that registers every subcommand; doing so cheaply (no
sub-imports run heavy modules until typer dispatches) keeps ``bioflow
--help`` snappy.

Subcommands (MVP scope):
  bioflow hw            Show detected hardware profile.
  bioflow doctor        Self-check the host (Docker, RAM, disk, registry, ...).
  bioflow tools         List tools available on this host (filtered by hw).
  bioflow recommend     Run a preset pipeline.
  bioflow custom        Interactively build a pipeline from compatible tools.
  bioflow run           Execute a pipeline config file (auto-resumes).
  bioflow status        Show checkpoint state for a workspace.
  bioflow db            Fetch / manage reference databases.
  bioflow update        Run the monthly registry update workflow.
  bioflow ncbi          Search / download genomes & proteins from NCBI.
  bioflow recipe        List or run a curated end-to-end recipe.
  bioflow cite          Citations + DOIs for the tools a recipe / tool uses.
  bioflow provenance    Inspect a recipe run's recorded provenance.
  bioflow llm           Opt-in LLM companion (explain / diagnose / …).
  bioflow setup         First-time LLM backend wizard.
"""
from __future__ import annotations

from bioflow.cli._app import app

# Each import registers its commands via @app.command(...) side effects.
from bioflow.cli import (  # noqa: F401,E402
    cite,
    cohort,
    db,
    doctor,
    hw,
    llm,
    ncbi,
    overview,
    pipelines,
    provenance,
    recipe,
    setup,
    update,
)

# Public surface — kept stable for the test suite + console script entry.
from bioflow.cli.recipe import _parse_recipe_extra  # noqa: F401,E402


__all__ = ["app", "_parse_recipe_extra"]


if __name__ == "__main__":
    app()
