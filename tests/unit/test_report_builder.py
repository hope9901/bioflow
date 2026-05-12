"""Phase 2E — `bioflow.report.Report` builder tests.

Different from the existing test_report.py which covers the older
`bioflow.core.report` pipeline-summary helper.  This file targets the
new accumulator API.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


from bioflow import Report


# ---------------------------------------------------------------------------
# Basic build / write
# ---------------------------------------------------------------------------

class TestBasicBuild:

    def test_empty_report_renders(self, tmp_path):
        rep = Report(title="Empty", out_dir=tmp_path)
        out = rep.write()
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "Empty" in text
        assert "0 sections" in text

    def test_default_path_is_summary_html(self, tmp_path):
        rep = Report(title="x", out_dir=tmp_path)
        out = rep.write()
        assert out.name == "summary.html"
        assert out.parent == tmp_path

    def test_custom_path_honoured(self, tmp_path):
        rep = Report(title="x", out_dir=tmp_path)
        target = tmp_path / "subdir" / "custom.html"
        out = rep.write(path=target)
        assert out == target
        assert target.exists()

    def test_lf_line_endings(self, tmp_path):
        rep = Report(title="x", out_dir=tmp_path)
        rep.add_text("hello")
        out = rep.write()
        raw = out.read_bytes()
        # No CR bytes anywhere — important for cross-tool compatibility
        assert b"\r\n" not in raw


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

class TestSections:

    def test_section_with_body_text(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("Step 1", body="Did the thing.")
        text = rep.write().read_text(encoding="utf-8")
        assert "Step 1" in text
        assert "Did the thing." in text

    def test_section_auto_numbered(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("First")
        rep.add_section("Second")
        rep.add_section("Third")
        text = rep.write().read_text(encoding="utf-8")
        assert ">1.<" in text
        assert ">2.<" in text
        assert ">3.<" in text

    def test_html_escape_in_body(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("danger", body="<script>alert('xss')</script>")
        text = rep.write().read_text(encoding="utf-8")
        assert "<script>alert" not in text
        assert "&lt;script&gt;" in text

    def test_html_escape_in_title(self, tmp_path):
        rep = Report(title="<bad>", out_dir=tmp_path)
        text = rep.write().read_text(encoding="utf-8")
        assert "&lt;bad&gt;" in text

    def test_code_block_is_escaped_and_in_pre(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("cmd", code="echo <hi>")
        text = rep.write().read_text(encoding="utf-8")
        assert "<pre>" in text
        assert "echo &lt;hi&gt;" in text


# ---------------------------------------------------------------------------
# Stage-result chips
# ---------------------------------------------------------------------------

class TestStageResultRendering:

    def _fake_results(self, n_total, n_cached, n_failed):
        results = []
        for i in range(n_total):
            ok = i >= n_failed
            cached = i < n_cached
            results.append(SimpleNamespace(
                out_dir=Path(f"/tmp/sample_{i}"),
                cached=cached, ok=ok,
            ))
        return results

    def test_chip_counts(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("Annotation", results=self._fake_results(10, 3, 1))
        text = rep.write().read_text(encoding="utf-8")
        assert "10 stage results" in text
        assert "cached=3" in text
        assert "failed=1" in text

    def test_dir_truncation(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("Lots", results=self._fake_results(20, 0, 0))
        text = rep.write().read_text(encoding="utf-8")
        assert "sample_0" in text
        assert "sample_4" in text
        assert "sample_19" not in text
        assert "+ 15 more" in text

    def test_empty_results_not_crashing(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("Empty", results=[])
        text = rep.write().read_text(encoding="utf-8")
        assert "no stage results" in text


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

class TestFigures:

    def _make_fig(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(2, 2))
        ax.plot([1, 2, 3], [1, 4, 9])
        return fig

    def test_figure_saved_under_figures_dir(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        path = rep.add_figure("Demo", fig=self._make_fig())
        assert path.exists()
        assert path.parent == tmp_path / "figures"
        assert path.suffix == ".png"

    def test_figure_referenced_in_html(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_figure("My Plot", fig=self._make_fig())
        text = rep.write().read_text(encoding="utf-8")
        assert 'src="figures/my_plot.png"' in text


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class TestTables:

    def _make_df(self, n=5):
        import pandas as pd
        return pd.DataFrame({"id": range(n), "x": [i * 2 for i in range(n)]})

    def test_table_renders(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_table("My Data", self._make_df(5))
        text = rep.write().read_text(encoding="utf-8")
        assert '<table' in text
        assert "<th>id</th>" in text
        assert "<td>0</td>" in text

    def test_table_truncates_to_max_rows(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_table("Big", self._make_df(100), max_rows=3)
        text = rep.write().read_text(encoding="utf-8")
        assert "<td>0</td>" in text
        assert "<td>2</td>" in text
        assert "97 rows truncated" in text


# ---------------------------------------------------------------------------
# Re-write idempotency
# ---------------------------------------------------------------------------

class TestRewrite:

    def test_calling_write_twice_overwrites(self, tmp_path):
        rep = Report(title="t", out_dir=tmp_path)
        rep.add_section("First")
        out1 = rep.write()
        size_1 = out1.stat().st_size

        rep.add_section("Second")
        out2 = rep.write()
        assert out2 == out1
        assert out2.stat().st_size > size_1
        text = out2.read_text(encoding="utf-8")
        assert "First" in text and "Second" in text
