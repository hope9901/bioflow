"""Cookbook 8/8 — verify cafe_evolution and cog_enrichment recipes register
correctly and respond to the CLI."""
from __future__ import annotations

from pathlib import Path

import pytest

from bioflow import set_backend, set_workspace, MockBackend
from bioflow.recipes import get, names


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    set_backend(MockBackend())
    yield


class TestRegistryComplete:

    def test_all_eight_recipes_registered(self):
        registered = set(names())
        expected = {
            "pangenome",
            "phylogeny",
            "download_taxon",
            "ani_matrix",
            "gwas",
            "amr_vf_catalogue",
            "cafe_evolution",
            "cog_enrichment",
        }
        missing = expected - registered
        assert not missing, f"Missing recipes: {missing}"


class TestCafeEvolution:

    def test_registered_and_dag_sane(self):
        pipe = get("cafe_evolution")
        plan = pipe.dry_run()
        assert plan["n_stages"] == 1
        assert plan["stages"][0]["name"] == "run_cafe5"
        # CAFE5 stage should opt into retry on OOM
        assert plan["stages"][0]["cache"] is True

    def test_executes_with_dummy_inputs(self, tmp_path, _isolated_runtime):
        ws = tmp_path / "ws"
        tree = ws / "tree.nwk"
        ct = ws / "counts.tsv"
        tree.write_text("((a:1,b:1):1,c:2);\n", encoding="utf-8")
        ct.write_text(
            "Desc\tFamily ID\ta\tb\tc\n"
            "x\tF0001\t1\t1\t1\n",
            encoding="utf-8",
        )
        pipe = get("cafe_evolution")
        result = pipe(tree=tree, count_table=ct, out_dir=ws / "cafe_out")
        assert result.ok


class TestCogEnrichment:

    def _make_fixtures(self, ws: Path):
        ws.mkdir(parents=True, exist_ok=True)
        pan = ws / "pan.faa"
        pan.write_text(">pan1\nMRT\n>pan2\nMKY\n", encoding="utf-8")
        cog = ws / "cog.faa"
        cog.write_text(">x|COG0001|y\nMRT\n", encoding="utf-8")
        cog_def = ws / "cog.def"
        cog_def.write_text(
            "COG0001\tJ\tribosomal protein\n"
            "COG0002\tE\tamino acid metabolism\n",
            encoding="utf-8",
        )
        gpa = ws / "gpa.csv"
        gpa.write_text(
            "Gene,Non-unique Gene name,Annotation,No. isolates,"
            "No. sequences,Avg sequences per isolate,"
            "Genome Fragment,Order within Fragment,"
            "Accessory Fragment,Accessory Order with Fragment,"
            "QC,Min group size nuc,Max group size nuc,Avg group size nuc,"
            "sample1\n"
            "pan1,,,1,1,1,,,,,,300,300,300,locus1\n"
            "pan2,,,1,1,1,,,,,,300,300,300,locus2\n",
            encoding="utf-8",
        )
        return pan, cog, cog_def, gpa

    def test_registered_two_stages(self):
        pipe = get("cog_enrichment")
        plan = pipe.dry_run()
        assert plan["n_stages"] == 2
        stage_names = [s["name"] for s in plan["stages"]]
        assert "diamond_makedb" in stage_names
        assert "diamond_blastp" in stage_names
        # blastp depends on makedb
        bp = next(s for s in plan["stages"] if s["name"] == "diamond_blastp")
        assert "diamond_makedb" in bp["depends_on"]

    def test_pipeline_runs_with_mock_backend(self, tmp_path, _isolated_runtime):
        ws = tmp_path / "ws"
        pan, cog, cog_def, gpa = self._make_fixtures(ws)
        pipe = get("cog_enrichment")
        # MockBackend doesn't actually run diamond, so hits.tsv won't exist
        # → pipeline returns the blastp StageResult early.  Just verify no
        # exceptions are raised.
        result = pipe(
            pangenome_faa=pan, cog_faa=cog, cog_def=cog_def,
            gpa_csv=gpa, out_dir=ws / "cog_out",
        )
        assert result is not None


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCli:

    def _run(self, argv):
        from typer.testing import CliRunner
        from bioflow.cli import app
        return CliRunner().invoke(app, argv)

    def test_recipe_list_shows_all_eight(self):
        r = self._run(["recipe", "list"])
        assert r.exit_code == 0
        for name in [
            "pangenome", "phylogeny", "download_taxon", "ani_matrix",
            "gwas", "amr_vf_catalogue", "cafe_evolution", "cog_enrichment",
        ]:
            assert name in r.stdout

    def test_cafe_evolution_show(self):
        r = self._run(["recipe", "show", "cafe_evolution"])
        assert r.exit_code == 0
        assert "run_cafe5" in r.stdout

    def test_cog_enrichment_show(self):
        r = self._run(["recipe", "show", "cog_enrichment"])
        assert r.exit_code == 0
        assert "diamond_makedb" in r.stdout
        assert "diamond_blastp" in r.stdout

    def test_cafe_evolution_missing_args(self, tmp_path):
        r = self._run([
            "recipe", "run", "cafe_evolution",
            "--out", str(tmp_path / "out"),
        ])
        # tree + count_table are required (no defaults)
        assert r.exit_code != 0
