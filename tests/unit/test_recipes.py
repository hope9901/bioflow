"""Phase 3 — recipe registry + CLI bridge tests."""
from __future__ import annotations


import pytest

from bioflow import set_backend, set_workspace, MockBackend
from bioflow.recipes import RECIPES, get, names, register
from bioflow.sdk import Pipeline


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    backend = MockBackend()
    set_backend(backend)
    yield backend


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:

    def test_pangenome_auto_registered(self):
        assert "pangenome" in names()
        pipe = get("pangenome")
        assert isinstance(pipe, Pipeline)
        assert pipe.name == "pangenome"
        assert len(pipe.stages) == 2

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown recipe"):
            get("nonexistent")

    def test_register_rejects_non_pipeline(self):
        with pytest.raises(TypeError):
            register("bad", "not_a_pipeline")

    def test_register_rejects_duplicate(self):
        from bioflow.sdk import pipeline as _pipeline
        @_pipeline()
        def custom():
            return None

        register("dup_recipe", custom)
        with pytest.raises(ValueError, match="already registered"):
            @_pipeline()
            def other():
                return None
            register("dup_recipe", other)
        # Re-registering the same object is fine (idempotent)
        register("dup_recipe", custom)
        # cleanup
        RECIPES.pop("dup_recipe", None)

    def test_get_is_case_insensitive(self):
        assert get("PANGENOME") is get("pangenome")
        assert get("PangeNome") is get("pangenome")


# ---------------------------------------------------------------------------
# Pipeline structure (DAG, dry_run)
# ---------------------------------------------------------------------------

class TestPangenomeStructure:

    def test_stages_in_correct_order(self):
        pipe = get("pangenome")
        order = pipe.topological_order()
        assert [s.name for s in order] == ["annotate", "run_roary"]

    def test_dry_run_sane(self):
        pipe = get("pangenome")
        plan = pipe.dry_run()
        assert plan["pipeline"] == "pangenome"
        assert plan["n_stages"] == 2
        assert plan["total_cpu"] == 10   # 2 + 8
        # run_roary depends on annotate
        roary_plan = next(s for s in plan["stages"] if s["name"] == "run_roary")
        assert roary_plan["depends_on"] == ["annotate"]


# ---------------------------------------------------------------------------
# End-to-end with stub inputs (no NCBI fetch)
# ---------------------------------------------------------------------------

class TestPangenomeExecution:

    def test_runs_with_genome_paths_escape_hatch(
        self, tmp_path, _isolated_runtime,
    ):
        # Make a few stub FASTA files inside the workspace
        ws = tmp_path / "ws"
        gdir = ws / "fakes"
        gdir.mkdir(parents=True, exist_ok=True)
        stubs = []
        for i in range(3):
            p = gdir / f"genome_{i}.fna"
            p.write_text(f">seq_{i}\nACGTACGT\n")
            stubs.append(p)

        pipe = get("pangenome")
        result = pipe(
            taxon="(stub)",
            out_dir=ws,
            _genome_paths=stubs,
        )
        assert result.ok
        # 3 annotate calls + 1 roary call
        cmds = [c["command"] for c in _isolated_runtime.calls]
        n_prokka = sum(1 for c in cmds if c.startswith("prokka"))
        n_roary = sum(1 for c in cmds if "roary " in c)
        assert n_prokka == 3
        assert n_roary == 1

    def test_empty_inputs_raises_clean(self, tmp_path, _isolated_runtime):
        pipe = get("pangenome")
        with pytest.raises(RuntimeError, match="No genomes found"):
            pipe(
                taxon="(stub)",
                out_dir=tmp_path / "ws",
                _genome_paths=[],   # explicitly empty
            )


# ---------------------------------------------------------------------------
# CLI bridge
# ---------------------------------------------------------------------------

class TestCliBridge:

    def _runner(self):
        from typer.testing import CliRunner
        from bioflow.cli import app
        return CliRunner(), app

    def test_recipe_list_shows_pangenome(self):
        runner, app = self._runner()
        r = runner.invoke(app, ["recipe", "list"])
        assert r.exit_code == 0
        assert "pangenome" in r.stdout

    def test_recipe_show_renders_dag(self):
        runner, app = self._runner()
        r = runner.invoke(app, ["recipe", "show", "pangenome"])
        assert r.exit_code == 0
        assert "annotate" in r.stdout
        assert "run_roary" in r.stdout

    def test_recipe_run_dry_does_not_execute(self):
        runner, app = self._runner()
        r = runner.invoke(
            app,
            ["recipe", "run", "pangenome",
             "--taxon", "Dickeya", "--dry-run"],
        )
        assert r.exit_code == 0
        assert "Dry-run" in r.stdout
        assert "annotate" in r.stdout

    def test_recipe_run_unknown_recipe_fails_cleanly(self):
        runner, app = self._runner()
        r = runner.invoke(app, ["recipe", "run", "no_such_recipe"])
        assert r.exit_code != 0
        assert "Unknown recipe" in r.stdout

    def test_recipe_run_missing_required_arg_fails_cleanly(self, tmp_path):
        runner, app = self._runner()
        # pangenome needs --taxon when no _genome_paths is supplied
        r = runner.invoke(
            app,
            ["recipe", "run", "pangenome",
             "--out", str(tmp_path / "ws"),
             "--max", "0"],
        )
        # No taxon provided → should fail before touching Docker
        assert r.exit_code != 0
        assert "taxon" in r.stdout or "required" in r.stdout.lower()
