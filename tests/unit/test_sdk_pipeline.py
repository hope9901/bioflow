"""Phase 1D — depends_on metadata + @pipeline composition tests."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from bioflow import (
    stage,
    pipeline,
    Stage,
    Pipeline,
    set_workspace,
    set_backend,
    MockBackend,
)


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    backend = MockBackend()
    set_backend(backend)
    yield backend


# ---------------------------------------------------------------------------
# depends_on metadata
# ---------------------------------------------------------------------------

class TestDependsOnMetadata:

    def test_no_depends_on_default(self):
        @stage(image="x:1", cache=False)
        def s(x): return f"echo {x}"
        assert s.depends_on == ()

    def test_single_dep_normalised_to_tuple(self):
        @stage(image="x:1", cache=False)
        def upstream(x): return f"echo {x}"

        @stage(image="x:2", cache=False, depends_on=upstream)
        def downstream(x): return f"echo {x}"

        assert downstream.depends_on == (upstream,)

    def test_iterable_dep_accepted(self):
        @stage(image="x:1", cache=False)
        def a(x): return "echo a"

        @stage(image="x:1", cache=False)
        def b(x): return "echo b"

        @stage(image="x:1", cache=False, depends_on=[a, b])
        def c(x): return "echo c"

        assert c.depends_on == (a, b)

    def test_non_stage_dep_raises(self):
        with pytest.raises(TypeError, match="depends_on must contain Stage"):
            @stage(image="x:1", cache=False, depends_on=["not_a_stage"])
            def bad(x): return "echo x"


# ---------------------------------------------------------------------------
# @pipeline decorator basics
# ---------------------------------------------------------------------------

class TestPipelineDecorator:

    def test_pipeline_is_callable(self, _isolated_runtime):
        @stage(image="x:1", cache=False)
        def s(x): return f"echo {x}"

        @pipeline(stages=[s])
        def my_pipeline(items):
            return s.map(items, parallel=2)

        assert isinstance(my_pipeline, Pipeline)
        results = my_pipeline([1, 2, 3])
        assert len(results) == 3
        assert all(r.ok for r in results)

    def test_pipeline_name_defaults_to_func(self):
        @pipeline()
        def my_pipeline():
            return None
        assert my_pipeline.name == "my_pipeline"

    def test_pipeline_explicit_name(self):
        @pipeline(name="custom_name")
        def whatever():
            return None
        assert whatever.name == "custom_name"

    def test_pipeline_description_from_docstring(self):
        @pipeline()
        def my_pipeline():
            """Compute pangenome from a list of genomes."""
            return None
        assert "pangenome" in my_pipeline.description

    def test_run_alias_works(self, _isolated_runtime):
        @stage(image="x:1", cache=False)
        def s(x): return f"echo {x}"

        @pipeline()
        def my_pipeline(item):
            return s(item)

        # __call__ and .run should both work
        r1 = my_pipeline(1)
        r2 = my_pipeline.run(2)
        assert r1.ok and r2.ok

    def test_invalid_stage_in_decl_raises(self):
        with pytest.raises(TypeError, match="must contain Stage objects"):
            @pipeline(stages=["not_a_stage"])
            def bad():
                pass


# ---------------------------------------------------------------------------
# DAG inspection
# ---------------------------------------------------------------------------

class TestDagInspection:

    def _build(self):
        @stage(image="x:1", cache=False)
        def fetch(x): return f"echo {x}"

        @stage(image="x:1", cache=False, depends_on=fetch)
        def annotate(x): return f"echo {x}"

        @stage(image="x:1", cache=False, depends_on=annotate)
        def pangenome(x): return f"echo {x}"

        @stage(image="x:1", cache=False, depends_on=annotate)
        def phylogeny(x): return f"echo {x}"

        @pipeline(stages=[fetch, annotate, pangenome, phylogeny])
        def my_pipe(x):
            return None

        return my_pipe, (fetch, annotate, pangenome, phylogeny)

    def test_dag_includes_all_declared_stages(self):
        p, (fetch, annotate, pangenome, phylogeny) = self._build()
        graph = p.dag()
        assert fetch in graph and annotate in graph
        assert pangenome in graph and phylogeny in graph
        assert graph[fetch] == []
        assert graph[annotate] == [fetch]
        assert graph[pangenome] == [annotate]
        assert graph[phylogeny] == [annotate]

    def test_dag_discovers_transitive_deps(self):
        @stage(image="x:1", cache=False)
        def root(x): return "echo root"

        @stage(image="x:1", cache=False, depends_on=root)
        def mid(x): return "echo mid"

        @stage(image="x:1", cache=False, depends_on=mid)
        def leaf(x): return "echo leaf"

        # Only declare the leaf — root and mid should still appear
        @pipeline(stages=[leaf])
        def p(x):
            return None

        graph = p.dag()
        assert root in graph
        assert mid in graph

    def test_topological_order_correct(self):
        p, (fetch, annotate, pangenome, phylogeny) = self._build()
        order = p.topological_order()
        assert order.index(fetch) < order.index(annotate)
        assert order.index(annotate) < order.index(pangenome)
        assert order.index(annotate) < order.index(phylogeny)

    def test_cycle_raises_on_topo_sort(self):
        # Construct stages with a cycle by post-mutating depends_on
        @stage(image="x:1", cache=False)
        def a(x): return "echo a"

        @stage(image="x:1", cache=False, depends_on=a)
        def b(x): return "echo b"

        # Inject cycle: a depends on b, b depends on a
        a.depends_on = (b,)

        @pipeline(stages=[a, b])
        def p(): pass

        with pytest.raises(ValueError, match="Cycle"):
            p.topological_order()


class TestShowGraphAndDryRun:

    def test_show_graph_emits_topological_render(self, capsys):
        @stage(image="img:v1", cpu=2, ram_gb=4, cache=False)
        def fetch(x): return "echo"

        @stage(image="img:v2", cpu=4, ram_gb=8, cache=False,
               depends_on=fetch)
        def process(x): return "echo"

        @pipeline(stages=[fetch, process],
                  description="Demo pipeline")
        def demo(x): return None

        out = demo.show_graph()
        captured = capsys.readouterr().out
        assert "Demo pipeline" in out
        assert "fetch" in out
        assert "process" in out
        # process must appear AFTER fetch in render
        assert out.index("process") > out.index("fetch")
        # Both written to stdout AND returned
        assert captured.strip() == out.strip()

    def test_dry_run_returns_summary_dict(self):
        @stage(image="img:v1", cpu=2, ram_gb=4, cache=False)
        def fetch(x): return "echo"

        @stage(image="img:v2", cpu=4, ram_gb=8, cache=False,
               depends_on=fetch)
        def process(x): return "echo"

        @pipeline(stages=[fetch, process], description="Demo")
        def demo(x): return None

        plan = demo.dry_run()
        assert plan["pipeline"] == "demo"
        assert plan["n_stages"] == 2
        assert plan["total_cpu"] == 6
        assert plan["total_ram_gb"] == 12
        assert [s["name"] for s in plan["stages"]] == ["fetch", "process"]
        assert plan["stages"][1]["depends_on"] == ["fetch"]


# ---------------------------------------------------------------------------
# Composition with map / starmap (real chaining)
# ---------------------------------------------------------------------------

class TestRealChaining:

    def test_two_stage_pipeline_threads_results(self, _isolated_runtime):
        @stage(image="x:1", cache=False)
        def annotate(genome): return f"echo annot {genome}"

        @stage(image="x:2", cache=False, depends_on=annotate)
        def pangenome(annotated_results):
            n = len(annotated_results)
            return f"echo pan over {n} genomes"

        @pipeline(stages=[annotate, pangenome])
        def comp_genomics(genomes):
            annot = annotate.map(genomes, parallel=2)
            return pangenome(annot)

        result = comp_genomics(["g1", "g2", "g3"])
        assert result.ok
        cmds = [c["command"] for c in _isolated_runtime.calls]
        # 3 annotate calls + 1 pangenome call
        assert sum(1 for c in cmds if c.startswith("echo annot")) == 3
        assert sum(1 for c in cmds if c.startswith("echo pan over 3")) == 1

    def test_pipeline_logs_start_and_done(
        self, _isolated_runtime, caplog,
    ):
        import logging
        @stage(image="x:1", cache=False)
        def s(x): return f"echo {x}"

        @pipeline()
        def my_pipe(x):
            return s(x)

        with caplog.at_level(logging.INFO):
            my_pipe("hello")
        msgs = [r.message for r in caplog.records]
        assert any("PIPELINE  start" in m for m in msgs)
        assert any("PIPELINE  done" in m for m in msgs)
