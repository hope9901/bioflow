"""Unit tests for the cohort runner (samplesheet fan-out).

The orchestration is exercised with an injected ``run_one`` so nothing here
spawns a real subprocess, a container, or MultiQC.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bioflow.core import cohort
from bioflow.core.cohort import (
    CohortReport,
    SampleResult,
    read_samplesheet,
    run_cohort,
)


# ---------------------------------------------------------------------------
# read_samplesheet
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "samples.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_read_samplesheet_basic(tmp_path):
    sheet = _write(tmp_path, "sample_id,r1,r2\niso1,a_R1.fq,a_R2.fq\niso2,b_R1.fq,b_R2.fq\n")
    rows = read_samplesheet(sheet)
    assert [r["sample_id"] for r in rows] == ["iso1", "iso2"]
    assert rows[0] == {"sample_id": "iso1", "r1": "a_R1.fq", "r2": "a_R2.fq"}


def test_read_samplesheet_id_aliases_and_blanks(tmp_path):
    # 'sample' column (alias) + a blank row that should be skipped
    sheet = _write(tmp_path, "sample,r1\nx,1.fq\n\ny,2.fq\n")
    rows = read_samplesheet(sheet)
    assert [r["sample_id"] for r in rows] == ["x", "y"]


def test_read_samplesheet_missing_id_column(tmp_path):
    sheet = _write(tmp_path, "foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="needs a sample-id column"):
        read_samplesheet(sheet)


def test_read_samplesheet_duplicate_id(tmp_path):
    sheet = _write(tmp_path, "sample_id,r1\nx,1.fq\nx,2.fq\n")
    with pytest.raises(ValueError, match="Duplicate sample_id"):
        read_samplesheet(sheet)


def test_read_samplesheet_no_data_rows(tmp_path):
    sheet = _write(tmp_path, "sample_id,r1\n")
    with pytest.raises(ValueError, match="no data rows"):
        read_samplesheet(sheet)


# ---------------------------------------------------------------------------
# run_cohort orchestration (injected run_one)
# ---------------------------------------------------------------------------

class _Recorder:
    """Fake per-sample runner that records calls and succeeds by default."""

    def __init__(self, fail: "set[str] | None" = None):
        self.calls: "list[tuple[str, str, Path, dict]]" = []
        self.fail = fail or set()

    def __call__(self, recipe, sample_id, workspace, params) -> SampleResult:
        self.calls.append((recipe, sample_id, workspace, dict(params)))
        ok = sample_id not in self.fail
        return SampleResult(sample_id, ok, 0 if ok else 1, workspace)


def test_run_cohort_fans_out_per_sample(tmp_path):
    sheet = _write(tmp_path, "sample_id,r1,r2\niso1,a1,a2\niso2,b1,b2\n")
    rec = _Recorder()
    report = run_cohort(
        "prokaryote_assembly", sheet, tmp_path / "out",
        jobs=1, aggregate=False, run_one=rec,
    )
    assert isinstance(report, CohortReport)
    assert report.ok and report.n_ok == 2 and report.n_failed == 0
    # one call per sample, with the right recipe + per-sample workspace + params
    assert [c[1] for c in rec.calls] == ["iso1", "iso2"]
    assert rec.calls[0][0] == "prokaryote_assembly"
    assert rec.calls[0][2] == (tmp_path / "out" / "iso1")
    assert rec.calls[0][3] == {"r1": "a1", "r2": "a2"}


def test_run_cohort_common_params_merged_row_wins(tmp_path):
    sheet = _write(tmp_path, "sample_id,r1\nx,row.fq\n")
    rec = _Recorder()
    run_cohort(
        "germline_variants", sheet, tmp_path / "o",
        common={"reference": "ref.fa", "r1": "common.fq"},
        jobs=1, aggregate=False, run_one=rec,
    )
    params = rec.calls[0][3]
    assert params["reference"] == "ref.fa"     # shared param applied
    assert params["r1"] == "row.fq"            # per-sample column overrides common


def test_run_cohort_failure_isolation(tmp_path):
    sheet = _write(tmp_path, "sample_id,r1\na,1\nb,2\nc,3\n")
    rec = _Recorder(fail={"b"})
    report = run_cohort("x", sheet, tmp_path / "o", jobs=1, aggregate=False, run_one=rec)
    assert report.n_ok == 2 and report.n_failed == 1
    assert not report.ok
    assert {r.sample_id for r in report.results if not r.ok} == {"b"}
    # all three still attempted despite b failing
    assert len(rec.calls) == 3


def test_run_cohort_run_one_exception_is_contained(tmp_path):
    sheet = _write(tmp_path, "sample_id,r1\na,1\nb,2\n")

    def boom(recipe, sample_id, workspace, params):
        if sample_id == "a":
            raise RuntimeError("kaboom")
        return SampleResult(sample_id, True, 0, workspace)

    report = run_cohort("x", sheet, tmp_path / "o", jobs=1, aggregate=False, run_one=boom)
    assert report.n_failed == 1 and report.n_ok == 1
    bad = [r for r in report.results if not r.ok][0]
    assert "kaboom" in bad.error


def test_run_cohort_parallel_completes_all(tmp_path):
    rows = "".join(f"s{i},r{i}\n" for i in range(6))
    sheet = _write(tmp_path, "sample_id,r1\n" + rows)
    rec = _Recorder()
    report = run_cohort("x", sheet, tmp_path / "o", jobs=4, aggregate=False, run_one=rec)
    assert report.n_ok == 6
    assert sorted(r.sample_id for r in report.results) == [f"s{i}" for i in range(6)]


def test_run_cohort_aggregates_when_any_ok(tmp_path, monkeypatch):
    sheet = _write(tmp_path, "sample_id,r1\nx,1\n")
    called = {}
    monkeypatch.setattr(
        cohort, "_aggregate",
        lambda out_dir: called.setdefault("out", out_dir) or (out_dir / "rep.html"),
    )
    report = run_cohort("x", sheet, tmp_path / "o", jobs=1, aggregate=True, run_one=_Recorder())
    assert report.multiqc_report is not None
    assert called["out"] == (tmp_path / "o").resolve()


def test_run_cohort_skips_aggregate_when_all_fail(tmp_path, monkeypatch):
    sheet = _write(tmp_path, "sample_id,r1\nx,1\n")
    monkeypatch.setattr(cohort, "_aggregate", lambda out_dir: pytest.fail("should not aggregate"))
    report = run_cohort("x", sheet, tmp_path / "o", jobs=1, aggregate=True, run_one=_Recorder(fail={"x"}))
    assert report.multiqc_report is None


# ---------------------------------------------------------------------------
# QC staging for aggregation (the hidden-.cache fix)
# ---------------------------------------------------------------------------

def _make_sample_qc(out: Path, sid: str) -> None:
    """Write per-sample QC files under a hidden .cache dir, like a real run."""
    d = out / sid / ".cache" / f"qc_trim__{sid}hash"
    d.mkdir(parents=True)
    (d / "fastp.json").write_text("{}")
    (d / "report.tsv").write_text("metric\tvalue\n")
    asm = out / sid / ".cache" / f"assemble__{sid}"
    asm.mkdir(parents=True)
    (asm / "contigs.fasta").write_text(">c\nACGT\n")   # not a QC suffix → skipped


def test_stage_qc_mirrors_hidden_cache_into_visible_tree(tmp_path):
    out = tmp_path / "out"
    _make_sample_qc(out, "SC1")
    _make_sample_qc(out, "SC2")
    qc_root = out / "_cohort_qc"
    n = cohort._stage_qc(out, qc_root)
    assert n == 4   # 2 samples x (fastp.json + report.tsv); the .fasta is skipped
    staged = [p for p in qc_root.rglob("*") if p.is_file()]
    names = sorted(p.name for p in staged)
    # visible (no hidden path component) + sample-id-prefixed + suffix preserved
    assert not any(part.startswith(".") for p in staged for part in p.relative_to(qc_root).parts)
    assert any(n.startswith("SC1_") and n.endswith("fastp.json") for n in names)
    assert any(n.startswith("SC2_") and n.endswith("report.tsv") for n in names)


def test_stage_qc_skips_large_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cohort, "_QC_MAX_BYTES", 100)
    out = tmp_path / "out"
    d = out / "S" / ".cache" / "x"
    d.mkdir(parents=True)
    (d / "huge.txt").write_text("0" * 500)     # > 100-byte cap → skipped
    (d / "small.json").write_text("{}")
    assert cohort._stage_qc(out, out / "_cohort_qc") == 1


def test_aggregate_points_multiqc_at_visible_tree(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _make_sample_qc(out, "S1")
    captured: dict = {}
    import bioflow.core.report as report_mod
    monkeypatch.setattr(
        report_mod, "run_multiqc",
        lambda wd, od, **k: captured.update(wd=wd, od=od) or (od / "multiqc_report.html"),
    )
    res = cohort._aggregate(out)
    assert captured["wd"] == out / "_cohort_qc"       # scans staged tree, not raw out/
    assert res is not None


def test_aggregate_returns_none_without_qc(tmp_path):
    out = tmp_path / "out"
    (out / "S1").mkdir(parents=True)                  # sample dir but no QC files
    assert cohort._aggregate(out) is None
