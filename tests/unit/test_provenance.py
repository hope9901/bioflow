"""Run-provenance recording → provenance.json + ro-crate-metadata.json."""
from __future__ import annotations

import hashlib
import json

import pytest

from bioflow import MockBackend, set_backend, set_workspace, stage
from bioflow.core import provenance as prov


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    set_backend(MockBackend())
    # Each test starts with no active recorder.
    prov.set_recorder(None)
    yield
    prov.set_recorder(None)


# ---------------------------------------------------------------------------
# Hashing + input discovery
# ---------------------------------------------------------------------------

class TestHashing:

    def test_sha256_file_matches_hashlib(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_bytes(b"hello bioflow")
        assert prov.sha256_file(f) == hashlib.sha256(b"hello bioflow").hexdigest()

    def test_sha256_missing_file_is_none(self, tmp_path):
        assert prov.sha256_file(tmp_path / "nope") is None

    def test_collect_input_files_skips_outdir_and_dirs(self, tmp_path):
        f1 = tmp_path / "a.fq"; f1.write_text("x")
        f2 = tmp_path / "b.fq"; f2.write_text("y")
        d = tmp_path / "adir"; d.mkdir()
        files = prov._collect_input_files(
            (f1, d), {"r2": f2, "out_dir": tmp_path / "out"}
        )
        names = {p.name for p in files}
        assert names == {"a.fq", "b.fq"}        # dir + out_dir excluded


# ---------------------------------------------------------------------------
# Recorder is opt-in / zero-cost when off
# ---------------------------------------------------------------------------

class TestOptIn:

    def test_no_recorder_means_no_record(self, tmp_path):
        f = tmp_path / "in.fq"; f.write_text("data")

        @stage(image="alpine:3", cache=False)
        def step(x, *, out_dir):
            return f"cp {x} {out_dir}/out.txt"

        step(f)   # no recorder installed
        assert prov.get_recorder() is None

    def test_record_stage_noop_without_recorder(self):
        # Must not raise even with garbage args when disabled.
        prov.record_stage(
            name="x", image="img", command="c", exit_code=0, cached=False,
            out_dir="/tmp", started_at="t0", ended_at="t1",
            args=(), kwargs={},
        )  # no exception == pass


# ---------------------------------------------------------------------------
# Recording a real (mock-backed) run
# ---------------------------------------------------------------------------

class TestRecording:

    def _run_two_stage(self, tmp_path):
        f = tmp_path / "reads.fq"
        f.write_bytes(b"@r1\nACGT\n+\nIIII\n")

        @stage(image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0", cache=False)
        def qc(x, *, out_dir):
            return f"fastp -i {x} -o {out_dir}/clean.fq"

        rec = prov.ProvenanceRecorder(pipeline="demo", workspace=tmp_path / "ws")
        prov.set_recorder(rec)
        qc(f)
        prov.set_recorder(None)
        return rec, f

    def test_stage_recorded_with_input_hash(self, tmp_path):
        rec, f = self._run_two_stage(tmp_path)
        assert len(rec.stages) == 1
        s = rec.stages[0]
        assert s.name == "qc"
        assert s.exit_code == 0
        assert s.inputs, "expected an input file recorded"
        got = {i.path: i.sha256 for i in s.inputs}
        assert str(f) in got
        assert got[str(f)] == hashlib.sha256(f.read_bytes()).hexdigest()

    def test_mock_backend_digest_is_none(self, tmp_path):
        # MockBackend lacks _STREAMING_SUPPORTED, so no docker digest probe.
        rec, _ = self._run_two_stage(tmp_path)
        assert rec.stages[0].image_digest is None

    def test_cached_stage_is_recorded(self, tmp_path):
        f = tmp_path / "reads.fq"; f.write_bytes(b"data")

        @stage(image="alpine:3")    # cache=True (default)
        def qc(x, *, out_dir):
            return f"cp {x} {out_dir}/o"

        # First call populates the cache.
        qc(f)
        # Second call hits the cache; record it.
        rec = prov.ProvenanceRecorder(pipeline="demo", workspace=tmp_path / "ws")
        prov.set_recorder(rec)
        qc(f)
        prov.set_recorder(None)
        assert len(rec.stages) == 1
        assert rec.stages[0].cached is True


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

class TestWriters:

    def _recorder_with_one_stage(self, tmp_path):
        f = tmp_path / "g.fna"; f.write_text(">x\nACGT\n")
        rec = prov.ProvenanceRecorder(pipeline="pangenome", workspace=tmp_path)
        rec.add(prov.StageRecord(
            name="annotate", image="staphb/prokka:1.14.6",
            image_digest="sha256:" + "a" * 64,
            command="prokka ...", exit_code=0, cached=False,
            started_at="2026-06-08T00:00:00+00:00",
            ended_at="2026-06-08T00:01:00+00:00",
            out_dir=str(tmp_path / "annotate"),
            inputs=[prov.FileRef(path=str(f), sha256="deadbeef", size_bytes=8)],
        ))
        return rec

    def test_provenance_json_roundtrips(self, tmp_path):
        rec = self._recorder_with_one_stage(tmp_path)
        path = prov.write_provenance_json(rec)
        assert path.name == "provenance.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["pipeline"] == "pangenome"
        assert doc["stages"][0]["name"] == "annotate"
        assert doc["stages"][0]["image_digest"].startswith("sha256:")
        assert doc["stages"][0]["inputs"][0]["sha256"] == "deadbeef"

    def test_ro_crate_has_required_entities(self, tmp_path):
        rec = self._recorder_with_one_stage(tmp_path)
        path = prov.write_ro_crate(rec)
        assert path.name == "ro-crate-metadata.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["@context"].startswith("https://w3id.org/ro/crate/1.1")
        graph = doc["@graph"]
        types = [e.get("@type") for e in graph]
        # Metadata descriptor, root dataset, an action, an app, a file.
        assert "CreativeWork" in types
        assert "Dataset" in types
        assert "CreateAction" in types
        assert "SoftwareApplication" in types
        assert "File" in types
        # The metadata descriptor must conform to RO-Crate 1.1.
        meta = next(e for e in graph if e["@id"] == "ro-crate-metadata.json")
        assert meta["conformsTo"]["@id"] == "https://w3id.org/ro/crate/1.1"
        # The root dataset must reference the stage action.
        root = next(e for e in graph if e["@id"] == "./")
        assert root["hasPart"], "root dataset should list the stage action"

    def test_write_all_emits_both_files(self, tmp_path):
        rec = self._recorder_with_one_stage(tmp_path)
        written = prov.write_all(rec)
        names = {p.name for p in written}
        assert names == {"provenance.json", "ro-crate-metadata.json"}
        assert rec.ended_at is not None      # finish() was called


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def _invoke(argv):
    from typer.testing import CliRunner

    from bioflow.cli import app

    return CliRunner().invoke(app, argv)


class TestProvenanceCli:

    def test_show_missing_file_is_graceful(self, tmp_path):
        result = _invoke(["provenance", "show", str(tmp_path)])
        assert result.exit_code == 0
        assert "no provenance.json" in result.stdout

    def test_show_renders_stage(self, tmp_path):
        rec = prov.ProvenanceRecorder(pipeline="demo", workspace=tmp_path)
        rec.add(prov.StageRecord(
            name="qc", image="img:1", image_digest="sha256:" + "b" * 64,
            command="c", exit_code=0, cached=False,
            started_at="t0", ended_at="t1", out_dir=str(tmp_path / "qc"),
            inputs=[prov.FileRef(path=str(tmp_path / "r.fq"), sha256="abc123")],
        ))
        prov.write_provenance_json(rec)

        result = _invoke(["provenance", "show", str(tmp_path)])
        assert result.exit_code == 0
        assert "demo" in result.stdout
        assert "qc" in result.stdout

    def test_show_json(self, tmp_path):
        rec = prov.ProvenanceRecorder(pipeline="demo", workspace=tmp_path)
        rec.add(prov.StageRecord(
            name="qc", image="img:1", image_digest=None,
            command="c", exit_code=0, cached=False,
            started_at="t0", ended_at="t1", out_dir=str(tmp_path / "qc"),
        ))
        prov.write_provenance_json(rec)

        result = _invoke(["provenance", "show", str(tmp_path), "--json"])
        assert result.exit_code == 0
        doc = json.loads(result.stdout)
        assert doc["pipeline"] == "demo"
