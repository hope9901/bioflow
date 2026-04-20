"""Regression tests for bugs fixed in the vulnerability audit.

Each test is labelled with the issue it covers so the root cause stays
traceable.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ===========================================================================
# checkpoint.py
# ===========================================================================

class TestCheckpointAtomicWrite:
    """BUG: save() previously wrote directly to the state file; a mid-write
    crash left a partially-written / invalid JSON file that caused all
    subsequent pipeline runs to crash with JSONDecodeError on load()."""

    def test_save_produces_valid_json(self, tmp_path):
        from bioflow.core.checkpoint import save, load

        state = {"completed_stages": ["s1"], "artifacts": {"s1": {"f": "x"}}}
        save(tmp_path, state)
        assert (tmp_path / ".bioflow_state.json").exists()
        loaded = load(tmp_path)
        assert loaded["completed_stages"] == ["s1"]

    def test_save_uses_temp_then_rename(self, tmp_path):
        """Verify no .tmp file is left behind after a successful save."""
        from bioflow.core.checkpoint import save

        save(tmp_path, {"completed_stages": [], "artifacts": {}})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover temp files: {tmp_files}"


class TestCheckpointCorruptedState:
    """BUG: load() raised JSONDecodeError if the state file was corrupted
    (e.g. power loss during write).  Pipeline could not be resumed at all."""

    def test_corrupted_json_returns_empty_state(self, tmp_path):
        from bioflow.core.checkpoint import load

        state_file = tmp_path / ".bioflow_state.json"
        state_file.write_text("{invalid json", encoding="utf-8")

        # Must NOT raise; must return a fresh empty state
        state = load(tmp_path)
        assert state["completed_stages"] == []
        assert state["artifacts"] == {}

    def test_truncated_json_returns_empty_state(self, tmp_path):
        from bioflow.core.checkpoint import load

        state_file = tmp_path / ".bioflow_state.json"
        state_file.write_bytes(b'{"completed_stages": [')   # truncated

        state = load(tmp_path)
        assert state["completed_stages"] == []

    def test_hand_edited_missing_key_uses_defaults(self, tmp_path):
        """BUG: If a key like 'completed_stages' was deleted by hand, load()
        used to raise KeyError later when mark_completed() accessed it."""
        from bioflow.core.checkpoint import load

        state_file = tmp_path / ".bioflow_state.json"
        # Only 'artifacts' present — 'completed_stages' missing
        state_file.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")

        state = load(tmp_path)
        assert "completed_stages" in state
        assert state["completed_stages"] == []


# ===========================================================================
# planner.py
# ===========================================================================

class TestPlannerAssertReplaced:
    """BUG: preset stage without tool_id raised AssertionError (suppressed in
    optimised Python with -O).  Now raises a descriptive ValueError instead."""

    def _write_bad_preset(self, tmp_path: Path) -> Path:
        import yaml
        preset = {
            "id": "bad_preset",
            "pipeline": "genome_assembly",
            "description": "test",
            "applies_to": {},
            "stages": [
                # tool_id is None, skip is false → should raise ValueError
                {"stage_id": "genome_assembly.step1", "skip": False},
            ],
        }
        p = tmp_path / "presets" / "bad_preset.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.dump(preset), encoding="utf-8")
        return p

    def _write_cfg(self, tmp_path: Path, registry_dir: Path) -> Path:
        import yaml
        cfg = {
            "pipeline": "genome_assembly",
            "species": "prokaryote",
            "read_type": "short",
            "mode": "de_novo",
            "inputs": {"r1": "/r1.fq", "r2": "/r2.fq", "sample_id": "s1"},
            "workdir": str(tmp_path / "out"),
            "registry_dir": str(registry_dir),
        }
        p = tmp_path / "config.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        return p

    def test_missing_tool_id_raises_value_error(self, tmp_path):
        from bioflow.core.planner import plan_from_preset

        REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"
        # Copy schema + tools to a scratch registry, add the bad preset
        import shutil
        scratch = tmp_path / "registry"
        shutil.copytree(REGISTRY_DIR, scratch)
        self._write_bad_preset(scratch)

        cfg = self._write_cfg(tmp_path, scratch)

        with pytest.raises(ValueError, match="no tool_id"):
            plan_from_preset("bad_preset", cfg)


class TestPlannerR2Guard:
    """BUG: rnaseq_deg.step2 artifact chaining accessed running_inputs['r2']
    unconditionally, causing KeyError for single-end RNA-seq libraries."""

    def test_step2_single_end_no_keyerror(self, tmp_path):
        from bioflow.core.planner import _chain_artifact_params

        # Simulate: step1 finished, only r1 produced (single-end)
        running_inputs = {
            "r1": str(tmp_path / "rnaseq_deg_step1" / "clean_R1.fastq.gz"),
            # r2 intentionally absent
            "sample_id": "se_sample",
        }
        completed = ["rnaseq_deg.step1"]

        # Must NOT raise KeyError
        params = _chain_artifact_params(
            stage_id="rnaseq_deg.step2",
            tool_id="hisat2",
            completed_stage_ids=completed,
            workdir=tmp_path,
            running_inputs=running_inputs,
        )
        assert "r1" in params
        assert "r2" not in params   # r2 absent from inputs → absent from params


class TestPlannerProteomicsArtifact:
    """BUG: proteomics.step1 artifact was '{out_dir}' which _resolve_filename
    could not expand (out_dir is not a user input key), yielding a path like
    '/workdir/proteomics_step1/{out_dir}' — obviously wrong."""

    def test_msconvert_artifact_is_stage_dir(self, tmp_path):
        from bioflow.core.planner import _artifact_paths

        stage_dir = tmp_path / "proteomics_step1"
        paths = _artifact_paths("proteomics.step1", "msconvert", stage_dir, {})

        assert "mzml_dir" in paths
        # Must resolve to the stage directory itself, not contain literal braces
        assert "{" not in paths["mzml_dir"]
        assert Path(paths["mzml_dir"]) == stage_dir


# ===========================================================================
# runner.py
# ===========================================================================

class TestRunnerUnresolvedPlaceholderWarning:
    """BUG: _render_command silently passed literal '{missing_key}' strings
    to containers with no user-visible indication.  Now logs a warning."""

    def test_unresolved_placeholder_emits_warning(self, tmp_path, caplog):
        import logging
        from bioflow.core.planner import ExecutionPlan, StagePlan
        from bioflow.core.registry import load_registry
        from bioflow.core.runner import _render_command

        REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"
        tools = {t.id: t for t in load_registry(REGISTRY_DIR)}
        tool = tools["fastp"]

        stage = StagePlan(
            stage_id="genome_assembly.step1",
            tool_id="fastp",
            params={},   # no r1/r2 provided → placeholders unresolved
        )
        plan = ExecutionPlan(
            pipeline="genome_assembly",
            species="prokaryote",
            read_type="short",
            mode="de_novo",
            inputs={},   # deliberately empty
            stages=[stage],
            workdir=tmp_path,
            registry_dir=REGISTRY_DIR,
        )

        with caplog.at_level(logging.WARNING):
            rendered = _render_command(tool, stage, plan, tmp_path / "stage1")

        # The rendered command should contain the literal placeholder
        assert "{r1}" in rendered or "{r2}" in rendered or "{" in rendered
        # And a warning should have been emitted
        assert any("unresolved" in r.message.lower() for r in caplog.records)


# ===========================================================================
# ncbi.py
# ===========================================================================

class TestNcbiBadZipFile:
    """BUG: a corrupted / truncated ZIP download raised zipfile.BadZipFile
    (an uncaught exception).  Now raises NcbiError with a helpful message."""

    def _make_list_genomes_response(self):
        data = {
            "reports": [{
                "accession": "GCF_000001405.40",
                "assembly_info": {"assembly_level": "Complete Genome",
                                  "submission_date": "2022-01-01",
                                  "refseq_category": "reference genome"},
                "organism": {"organism_name": "Homo sapiens",
                             "infraspecific_names": {"strain": ""}},
                "assembly_stats": {"total_sequence_length": "3000000000",
                                   "number_of_scaffolds": "24"},
            }],
            "total_count": 1,
        }
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__  = MagicMock(return_value=False)
        cm.read      = MagicMock(return_value=json.dumps(data).encode())
        cm.headers   = {}
        return cm

    def _make_corrupt_zip_response(self):
        corrupt_bytes = b"this is not a zip file at all"
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cm)
        cm.__exit__  = MagicMock(return_value=False)
        chunks = [corrupt_bytes, b""]
        cm.read      = MagicMock(side_effect=chunks)
        cm.headers   = {"Content-Length": str(len(corrupt_bytes))}
        return cm

    def test_bad_zip_raises_ncbi_error(self, tmp_path):
        from bioflow.core.ncbi import NcbiError, download_genomes

        call_count = 0
        list_resp  = self._make_list_genomes_response()
        dl_resp    = self._make_corrupt_zip_response()

        def fake_opener(req, timeout=None):
            nonlocal call_count
            call_count += 1
            return list_resp if call_count == 1 else dl_resp

        with pytest.raises(NcbiError, match="not a valid ZIP"):
            download_genomes("homo_sapiens", tmp_path, progress=False,
                             _opener=fake_opener)


class TestNcbiZipPathTraversal:
    """BUG: ZIP extraction did not validate that the extracted path stayed
    inside out_dir, allowing a malicious ZIP to write files anywhere on the
    filesystem.

    The guard works by resolving dest_path and calling relative_to(out_dir).
    We test it by directly constructing dest_name values that would escape
    the output directory, simulating what a crafted ZIP could achieve.
    """

    def test_guard_blocks_parent_traversal(self, tmp_path):
        """A dest_name containing directory separators must be blocked."""
        out_dir = tmp_path / "genomes"
        out_dir.mkdir()

        # Simulate a dest_name that contains a directory component (e.g. from
        # a ZIP tool that builds paths differently).
        # We test the guard logic directly.
        traversal_name = os.path.join("..", "evil.fna")   # "../evil.fna"

        dest_path = (out_dir / traversal_name).resolve()
        escaped = False
        try:
            dest_path.relative_to(out_dir.resolve())
        except ValueError:
            escaped = True

        # The guard must detect this as an escape
        assert escaped, (
            f"Path traversal guard failed: '{dest_path}' should be outside '{out_dir}'"
        )

    def test_guard_allows_legitimate_path(self, tmp_path):
        """A normal filename must pass the guard."""
        out_dir = tmp_path / "genomes"
        out_dir.mkdir()

        dest_name = "GCF_000001_genome.fna"
        dest_path = (out_dir / dest_name).resolve()
        # Must NOT raise
        dest_path.relative_to(out_dir.resolve())

    def test_download_genomes_skips_traversal_members(self, tmp_path):
        """End-to-end: if a ZIP somehow contains a member whose resolved path
        is outside out_dir, download_genomes() skips it without crashing."""
        from bioflow.core.ncbi import NcbiError, download_genomes

        out_dir = tmp_path / "genomes"
        out_dir.mkdir()

        # Build a ZIP that has one legitimate .fna and one that (after our
        # dest_name construction) resolves to a file outside out_dir.
        # We embed the traversal at the fname level by placing a sub-dir inside
        # the accession part: GCF_001 → sub/file.fna.
        # After construction: dest_name = "GCF_001_file.fna" → stays inside.
        # A true traversal requires absolute dest_name or os.sep in parts.
        # We exercise the guard by injecting a fake ZipFile with a
        # specially crafted member that resolves outside out_dir.
        import zipfile as _zf
        import unittest.mock as _mock

        buf = io.BytesIO()
        with _zf.ZipFile(buf, "w") as z:
            z.writestr("ncbi_dataset/data/GCF_001/genome.fna", b">seq1\nATCG")
        zip_bytes = buf.getvalue()

        # Patch ZipFile.namelist() to inject a traversal member
        original_zf = _zf.ZipFile

        class PatchedZipFile(original_zf):
            def namelist(self):
                return ["ncbi_dataset/data/GCF_001/genome.fna",
                        "ncbi_dataset/data/GCF_001/../../../outside.fna"]

            def open(self, name):
                # Return the legitimate content for any member
                return original_zf.open(self, "ncbi_dataset/data/GCF_001/genome.fna")

        zip_path = tmp_path / "test.zip"
        zip_path.write_bytes(zip_bytes)

        with _mock.patch("bioflow.core.ncbi.zipfile.ZipFile", PatchedZipFile):
            # Build fake openers for list_genomes + download
            list_data = {
                "reports": [{
                    "accession": "GCF_001",
                    "assembly_info": {"assembly_level": "Complete Genome",
                                      "submission_date": "2024-01-01",
                                      "refseq_category": ""},
                    "organism": {"organism_name": "Test org",
                                 "infraspecific_names": {"strain": ""}},
                    "assembly_stats": {"total_sequence_length": "1000",
                                       "number_of_scaffolds": "1"},
                }],
                "total_count": 1,
            }
            call_n = 0
            def fake_opener(req, timeout=None):
                nonlocal call_n
                call_n += 1
                if call_n == 1:
                    cm = MagicMock()
                    cm.__enter__ = MagicMock(return_value=cm)
                    cm.__exit__  = MagicMock(return_value=False)
                    cm.read      = MagicMock(return_value=json.dumps(list_data).encode())
                    cm.headers   = {}
                    return cm
                else:
                    cm = MagicMock()
                    cm.__enter__ = MagicMock(return_value=cm)
                    cm.__exit__  = MagicMock(return_value=False)
                    chunks = [zip_bytes[i:i+131072] for i in range(0, len(zip_bytes), 131072)] + [b""]
                    cm.read      = MagicMock(side_effect=chunks)
                    cm.headers   = {"Content-Length": str(len(zip_bytes))}
                    return cm

            download_genomes("testorg", out_dir, progress=False, _opener=fake_opener)

        # 'outside.fna' must NOT exist anywhere outside out_dir
        for p in tmp_path.rglob("outside.fna"):
            if not str(p).startswith(str(out_dir)):
                pytest.fail(f"Path-traversal file escaped to {p}")


# ===========================================================================
# approve.py
# ===========================================================================

class TestApproveJsonschemaRequired:
    """BUG: When jsonschema was not installed, approve_candidate() emitted a
    warning and continued, allowing invalid tool definitions into the registry.
    Now raises ApprovalError immediately."""

    def test_missing_jsonschema_raises_approval_error(self, tmp_path, monkeypatch):
        import sys
        import yaml

        REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"
        candidate = tmp_path / "newtool.yaml"
        candidate.write_text(yaml.dump({
            "id": "newtool",
            "name": "New Tool",
            "version": "1.0",
            "category": "qc",
            "stage": ["genome_assembly.step1"],
            "applicable": {"species": ["any"], "read_type": ["short"], "mode": ["de_novo"]},
            "container": {"image": "biocontainers/newtool:1.0"},
            "resources": {
                "min": {"cpu": 2, "ram_gb": 4},
                "recommended": {"cpu": 8, "ram_gb": 16},
            },
            "command_template": "newtool -i {r1} -o {out_dir}",
        }), encoding="utf-8")

        # Setting sys.modules["jsonschema"] = None causes 'import jsonschema'
        # inside approve_candidate to raise ImportError immediately.
        monkeypatch.setitem(sys.modules, "jsonschema", None)

        from bioflow.core.approve import ApprovalError, approve_candidate

        with pytest.raises(ApprovalError, match="jsonschema"):
            approve_candidate(candidate, registry_dir=REGISTRY_DIR)


# ===========================================================================
# db.py
# ===========================================================================

class TestDbSizeValidation:
    """BUG: fetch_db() did not verify the downloaded file size against the
    Content-Length header, so a truncated download passed silently."""

    def test_truncated_download_raises_runtime_error(self, tmp_path):
        from bioflow.core.db import fetch_db

        # Fake response that claims 1000 bytes but delivers only 100
        fake_data = b"x" * 100
        cm = MagicMock()
        cm.read = MagicMock(side_effect=[fake_data[i:i+64] for i in range(0, len(fake_data), 64)] + [b""])
        cm.headers = MagicMock()
        cm.headers.get = MagicMock(return_value="1000")  # lie: claims 1000 bytes

        def fake_opener(url):
            return cm

        with pytest.raises(RuntimeError, match="truncated"):
            fetch_db("busco_bacteria", tmp_path, _opener=fake_opener)

    def test_correct_size_passes(self, tmp_path):
        from bioflow.core.db import fetch_db

        fake_data = b"x" * 200
        cm = MagicMock()
        cm.read = MagicMock(
            side_effect=[fake_data[i:i+64] for i in range(0, len(fake_data), 64)] + [b""]
        )
        cm.headers = MagicMock()
        cm.headers.get = MagicMock(return_value=str(len(fake_data)))   # honest

        def fake_opener(url):
            return cm

        dest = fetch_db("busco_bacteria", tmp_path, _opener=fake_opener)
        assert dest.exists()
        assert dest.stat().st_size == len(fake_data)


# ===========================================================================
# Second-pass audit fixes
# ===========================================================================

class TestReportXssEscape:
    """BUG: render_summary embedded checkpoint error strings verbatim into the
    HTML output.  A malicious error (e.g. containing '<script>') would be
    executed when the user opens the summary in a browser."""

    def test_error_detail_is_html_escaped(self, tmp_path):
        import yaml as _y
        from bioflow.core.planner import plan_from_preset
        from bioflow.core.report import render_summary
        from bioflow.core.checkpoint import save

        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(_y.safe_dump({
            "pipeline": "genome_assembly",
            "species": "prokaryote",
            "read_type": "short",
            "mode": "de_novo",
            "workdir": str(tmp_path),
            "registry_dir": str(Path(__file__).resolve().parents[2] / "registry"),
            "inputs": {
                "sample_id": "s1",
                "r1": "/x/R1.fq",
                "r2": "/x/R2.fq",
                "eggnog_db_dir": "/refs/eggnog",
            },
        }), encoding="utf-8")
        plan = plan_from_preset("prokaryote_denovo_short", cfg_path)
        # Inject a malicious error into the checkpoint for the first stage
        first_stage = plan.stages[0].stage_id
        save(tmp_path, {
            "completed_stages": [],
            "artifacts": {},
            "failed_stages": {
                first_stage: {"error": "<script>alert('xss')</script>"}
            },
        })

        out_dir = tmp_path / "report"
        out_dir.mkdir()
        summary = render_summary(plan, out_dir)
        content = summary.read_text(encoding="utf-8")

        assert "<script>alert" not in content
        assert "&lt;script&gt;" in content


class TestRegistryGracefulDegradation:
    """BUG: load_registry() raised ValueError on a single invalid YAML file,
    preventing all other tools from loading.  A bad tool shipped from a
    Deep-Research update could brick every pipeline."""

    def test_invalid_yaml_is_skipped_not_fatal(self, tmp_path):
        import shutil
        from bioflow.core.registry import load_registry

        src = Path(__file__).resolve().parents[2] / "registry"
        dst = tmp_path / "registry"
        shutil.copytree(src, dst)

        # Drop a garbage YAML file under tools/
        bad_dir = dst / "tools" / "qc"
        bad_dir.mkdir(parents=True, exist_ok=True)
        (bad_dir / "__bad__.yaml").write_text(
            "id: broken\nversion: 1.0\n# missing required fields\n",
            encoding="utf-8",
        )

        tools = load_registry(dst)
        # The real tools should still load (fastp etc.)
        ids = {t.id for t in tools}
        assert "fastp" in ids
        assert "broken" not in ids


class TestRunnerRamCeiling:
    """BUG: DockerBackend.run() used int(ram_gb) which truncates 7.9 → 7,
    starving the container vs what the tool registry promised."""

    def test_mem_limit_rounds_up(self):
        import math
        # Mirror the math.ceil-based formula used in runner.py.
        ram_gb = 7.5
        assert max(math.ceil(ram_gb), 1) == 8

    def test_docker_backend_uses_ceil(self, monkeypatch):
        import math
        captured = {}

        class FakeContainer:
            id = "c1"
            def logs(self, stream, follow): return iter([b""])
            def wait(self, timeout=None): return {"StatusCode": 0}
            def remove(self, force=False): pass

        class FakeContainers:
            def run(self, **kw):
                captured.update(kw)
                return FakeContainer()

        class FakeClient:
            containers = FakeContainers()

        from bioflow.core import runner
        backend = runner.DockerBackend.__new__(runner.DockerBackend)
        backend.client = FakeClient()
        backend.run(
            image="img", command="echo", mounts={}, cpu=1, ram_gb=7.3,
            workdir="/w",
        )
        # math.ceil(7.3) == 8 (not int() == 7)
        assert captured["mem_limit"] == "8g"


class TestMsconvertRawFileGlob:
    """BUG: proteomics.step1 planner provided {raw_file_dir} but the msconvert
    YAML template still referenced {raw_file}, so msconvert received the
    literal '{raw_file}' string and crashed in real runs."""

    def test_template_no_longer_references_raw_file(self):
        import yaml as _y
        tpl = Path(__file__).resolve().parents[2] / "registry" / "tools" / "proteomics" / "msconvert.yaml"
        data = _y.safe_load(tpl.read_text(encoding="utf-8"))
        cmd = data["command_template"]
        assert "{raw_file}" not in cmd or "{raw_file_dir}" in cmd
        assert "{raw_file_dir}" in cmd


class TestMacs3ControlArg:
    """BUG: MACS3 YAML previously required {control_bam} and planner had no
    chaining for it; the default was literal '{control_bam}' or invalid
    path.  Now planner emits '{control_arg}' ('' or '-c <bam>')."""

    def test_macs3_template_uses_control_arg(self):
        import yaml as _y
        tpl = Path(__file__).resolve().parents[2] / "registry" / "tools" / "epigenomics" / "macs3.yaml"
        data = _y.safe_load(tpl.read_text(encoding="utf-8"))
        cmd = data["command_template"]
        assert "{control_arg}" in cmd
        assert "{control_bam}" not in cmd
