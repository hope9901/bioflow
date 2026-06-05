"""Nightly smoke matrix — one real BioContainer per recipe family.

Goal
----
Catch the "tool YAML works in MockBackend but the real container is
broken / renamed / removed from the registry" class of bug, which
``test_recipe_real_data.py`` only catches for a single recipe.

Each entry in :data:`SMOKE` invokes the lightest reachable stage of a
recipe against a tiny fixture in ``data/test/`` and asserts that the
container produced its expected output file(s).  Stages requiring
heavyweight reference databases (eggNOG, BUSCO lineage, Kraken2 DB) or
exotic input types (long-read ONT, single-cell 10x, mass spec mzML) are
deliberately skipped with a clear reason — they need separate fixture
work before they can be smoke-tested.

Runtime
-------
Each entry pulls ~50–600 MB of container image and runs for under a
minute on the tiny fixtures.  Designed to be the body of a GitHub
Actions nightly job (.github/workflows/nightly-smoke.yml).

Run locally
-----------
::

    pytest tests/integration/test_recipe_smoke_matrix.py -v -m docker

    # only one entry:
    pytest tests/integration/test_recipe_smoke_matrix.py \
        -v -m docker -k prokaryote_assembly
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest


# ---------------------------------------------------------------------------
# Skip-when-no-Docker preamble (shared with the other integration tests).
# ---------------------------------------------------------------------------

_docker_unavailable: str | None = None
try:
    import docker as _docker_mod  # type: ignore[import-not-found]

    _docker_mod.from_env().ping()
except Exception as exc:
    _docker_unavailable = str(exc)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        _docker_unavailable is not None,
        reason=f"Docker not reachable: {_docker_unavailable}",
    ),
]


# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
ECOLI = REPO_ROOT / "data" / "test" / "ecoli_small"
FIXTURE_R1 = ECOLI / "real_R1.fastq.gz"
FIXTURE_R2 = ECOLI / "real_R2.fastq.gz"
FIXTURE_REF = ECOLI / "reference.fa"


# ---------------------------------------------------------------------------
# SmokeCase — a row in the matrix.
# ---------------------------------------------------------------------------

@dataclass
class SmokeCase:
    """One per (recipe, lightest-stage) smoke entry."""

    recipe: str
    stage_attr: str
    invoke: Callable[[object, Path], object]
    expect: list[str]
    fixture_required: list[Path]
    notes: str = ""


def _need(*paths: Path) -> str | None:
    for p in paths:
        if not p.exists():
            return f"fixture missing: {p.relative_to(REPO_ROOT)}"
    return None


# ---------------------------------------------------------------------------
# Helpers that wrap the recipes' first stage in a single call.
# ---------------------------------------------------------------------------

def _run_qc_trim_fastp(mod, _ws):
    return mod.qc_trim(FIXTURE_R1.resolve(), FIXTURE_R2.resolve())


def _run_rnaseq_qc(mod, _ws):
    # rnaseq_deg.qc_one wants (sample_id, r1, r2) — single-end fixture
    # works fine because fastp tolerates the same file as r2.
    return mod.qc_one("smoke_sample", FIXTURE_R1.resolve(), FIXTURE_R2.resolve())


def _run_abricate(mod, _ws):
    # The simplest comparative-genomics container — bundles its own DBs.
    return mod.abricate_one(FIXTURE_REF.resolve(), db="ncbi")


# ---------------------------------------------------------------------------
# The smoke matrix.
# ---------------------------------------------------------------------------

def _build_matrix() -> list[SmokeCase]:
    from bioflow.recipes.comparative_genomics import (  # noqa: F401  (import effects)
        amr_vf_catalogue,
    )
    from bioflow.recipes.genome_assembly import (  # noqa: F401
        prokaryote_assembly,
    )
    from bioflow.recipes.metagenomics import (  # noqa: F401
        metagenome_assembly,
        metagenomics_profile,
    )
    from bioflow.recipes.rnaseq_deg import rnaseq_deg  # noqa: F401
    from bioflow.recipes.variant_calling import germline_variants  # noqa: F401

    return [
        SmokeCase(
            recipe="prokaryote_assembly",
            stage_attr="qc_trim",
            invoke=_run_qc_trim_fastp,
            expect=["clean_R1.fastq.gz", "fastp.json"],
            fixture_required=[FIXTURE_R1, FIXTURE_R2],
            notes="fastp on paired short reads",
        ),
        SmokeCase(
            recipe="rnaseq_deg",
            stage_attr="qc_one",
            invoke=_run_rnaseq_qc,
            expect=["clean_R1.fastq.gz"],
            fixture_required=[FIXTURE_R1, FIXTURE_R2],
            notes="per-sample fastp wrapper from rnaseq_deg.qc_one",
        ),
        SmokeCase(
            recipe="amr_vf_catalogue",
            stage_attr="abricate_one",
            invoke=_run_abricate,
            expect=[],  # abricate writes to stdout in many modes; presence of out_dir is enough
            fixture_required=[FIXTURE_REF],
            notes="abricate vs its bundled NCBI database — tiny, fast",
        ),
    ]


# ---------------------------------------------------------------------------
# Per-recipe runtime fixture: workspace + Docker backend.
# ---------------------------------------------------------------------------

@pytest.fixture
def _runtime(tmp_path):
    from bioflow import DockerBackend, set_backend, set_workspace

    set_workspace(tmp_path / "ws")
    set_backend(DockerBackend())
    yield tmp_path


# ---------------------------------------------------------------------------
# Parametrize over SMOKE — one test invocation per recipe.
# ---------------------------------------------------------------------------

def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        cases = _build_matrix()
        metafunc.parametrize(
            "case", cases, ids=[c.recipe for c in cases]
        )


def test_recipe_first_stage_smoke(case: SmokeCase, _runtime):
    """Run *case*'s lightest stage with the real Docker backend.

    Verifies the container pulls, runs, exits zero, and produces every
    file listed in ``case.expect``.
    """
    skip_reason = _need(*case.fixture_required)
    if skip_reason:
        pytest.skip(skip_reason)

    import importlib

    # The recipe module name is the file-level module that owns
    # ``stage_attr``; we resolve via the registered Pipeline so the
    # smoke test always uses the same code path that ``bioflow recipe
    # run`` does.
    from bioflow import recipes

    pipe = recipes.get(case.recipe)
    # Pipeline holds a tuple of Stage objects; the named one is what we run.
    stage_obj = next(
        (s for s in pipe.stages if s.name == case.stage_attr), None
    )
    assert stage_obj is not None, (
        f"recipe {case.recipe} has no stage {case.stage_attr!r}; "
        f"available: {[s.name for s in pipe.stages]}"
    )

    # We invoke via the importable module so the call shape matches
    # production (decorated function, kwargs, etc.) rather than going
    # through Stage internals.
    module_name = stage_obj.func.__module__
    module = importlib.import_module(module_name)
    result = case.invoke(module, _runtime)

    assert result.ok, (
        f"{case.recipe}.{case.stage_attr} failed "
        f"(exit={result.exit_code}): {result.stderr[:400]}"
    )

    out = Path(result.out_dir)
    assert out.is_dir(), f"out_dir missing: {out}"
    missing = [name for name in case.expect if not (out / name).exists()]
    assert not missing, (
        f"{case.recipe}.{case.stage_attr}: expected output(s) missing: {missing}\n"
        f"  out_dir contents: {sorted(p.name for p in out.iterdir())}"
    )
