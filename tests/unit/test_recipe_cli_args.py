"""BLOCKER-1 regression — `bioflow recipe run` must accept the inputs of
*every* recipe, not just the comparative-genomics ones whose options are
hardcoded in the CLI.

Before this fix, the recipe CLI had a hardcoded ``candidate`` dict +
fixed typer options, so the 8 per-pipeline recipes (prokaryote_assembly,
rnaseq_deg, …) could not receive ``--r1`` / ``--sample-sheet`` / etc. at
all — they were Python-API-only.
"""
from __future__ import annotations

import pytest

from bioflow import MockBackend, set_backend, set_workspace
from bioflow.cli import _parse_recipe_extra, app


def _run(argv):
    from typer.testing import CliRunner
    return CliRunner().invoke(app, argv)


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    set_backend(MockBackend())
    yield


class TestParseRecipeExtra:

    def test_space_separated_pairs(self):
        got = _parse_recipe_extra(["--r1", "a.fq", "--r2", "b.fq"])
        assert got == {"r1": "a.fq", "r2": "b.fq"}

    def test_equals_form(self):
        got = _parse_recipe_extra(["--transcriptome=ref.fa"])
        assert got == {"transcriptome": "ref.fa"}

    def test_dashes_become_underscores(self):
        got = _parse_recipe_extra(["--sample-id", "s1", "--kraken2-db", "/db"])
        assert got == {"sample_id": "s1", "kraken2_db": "/db"}

    def test_integer_coercion(self):
        got = _parse_recipe_extra(["--read-length", "150", "--cb-len", "16"])
        assert got == {"read_length": 150, "cb_len": 16}
        assert isinstance(got["read_length"], int)

    def test_paths_stay_strings(self):
        got = _parse_recipe_extra(["--r1", "/data/sample_R1.fastq.gz"])
        assert got["r1"] == "/data/sample_R1.fastq.gz"
        assert isinstance(got["r1"], str)

    def test_bare_flag(self):
        got = _parse_recipe_extra(["--verbose"])
        assert got == {"verbose": "true"}

    def test_empty(self):
        assert _parse_recipe_extra([]) == {}


class TestRecipeCliMissingArgs:

    def test_missing_required_lists_actual_params(self):
        # prokaryote_assembly requires r1, r2 — not taxon
        r = _run(["recipe", "run", "prokaryote_assembly", "--out", "x"])
        assert r.exit_code == 1
        assert "requires: r1, r2" in r.stdout
        # the misleading "Use --taxon, etc." hint is gone
        assert "--taxon" not in r.stdout
        # an actionable hint is shown instead
        assert "--r1 <value>" in r.stdout


class TestRecipeCliRunsPerPipelineRecipe:

    def test_prokaryote_assembly_runs_via_cli(self, tmp_path):
        r1 = tmp_path / "R1.fq.gz"
        r2 = tmp_path / "R2.fq.gz"
        r1.write_text("@r1", encoding="utf-8")
        r2.write_text("@r2", encoding="utf-8")

        r = _run([
            "recipe", "run", "prokaryote_assembly",
            "--out", str(tmp_path / "out"),
            "--r1", str(r1),
            "--r2", str(r2),
            "--sample-id", "demo",
        ])
        assert r.exit_code == 0, r.stdout
        assert "Recipe done" in r.stdout

    def test_metagenomics_profile_runs_via_cli(self, tmp_path):
        r1 = tmp_path / "R1.fq.gz"
        r2 = tmp_path / "R2.fq.gz"
        db = tmp_path / "k2db"
        r1.write_text("@r1", encoding="utf-8")
        r2.write_text("@r2", encoding="utf-8")
        db.mkdir()

        r = _run([
            "recipe", "run", "metagenomics_profile",
            "--out", str(tmp_path / "out"),
            "--r1", str(r1),
            "--r2", str(r2),
            "--kraken2-db", str(db),
            "--sample-id", "demo",
        ])
        assert r.exit_code == 0, r.stdout

    def test_unknown_option_warns_but_does_not_crash(self, tmp_path):
        r1 = tmp_path / "R1.fq.gz"
        r2 = tmp_path / "R2.fq.gz"
        r1.write_text("@r1", encoding="utf-8")
        r2.write_text("@r2", encoding="utf-8")

        r = _run([
            "recipe", "run", "prokaryote_assembly",
            "--out", str(tmp_path / "out"),
            "--r1", str(r1),
            "--r2", str(r2),
            "--bogus-option", "whatever",
        ])
        assert r.exit_code == 0, r.stdout
        assert "Ignored unknown option" in r.stdout
        assert "--bogus-option" in r.stdout
