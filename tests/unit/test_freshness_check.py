"""Unit tests for update/freshness_check.py — parsing, version
comparison, report rendering.  Network calls are stubbed."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "update"))

import freshness_check as fc   # noqa: E402


class TestParseImage:

    def test_quay_biocontainers(self):
        r = fc.parse_image("quay.io/biocontainers/fastp:0.23.4--h5f740d0_0")
        assert r == {
            "host": "quay.io", "owner": "biocontainers",
            "name": "fastp", "tag": "0.23.4--h5f740d0_0",
        }

    def test_docker_hub_two_segment(self):
        r = fc.parse_image("staphb/spades:4.0.0")
        assert r["host"] == "docker.io"
        assert r["owner"] == "staphb"
        assert r["name"] == "spades"
        assert r["tag"] == "4.0.0"

    def test_docker_hub_library(self):
        r = fc.parse_image("busybox:latest")
        assert r == {
            "host": "docker.io", "owner": "library",
            "name": "busybox", "tag": "latest",
        }

    def test_garbage(self):
        assert fc.parse_image("not an image") is None


class TestVersionCompare:

    def test_numeric_bump(self):
        assert fc.find_newer_tags("1.2.3", ["1.2.4", "1.2.3", "1.1.0"]) == ["1.2.4"]

    def test_major_bump(self):
        assert "2.0.0" in fc.find_newer_tags("1.9.9", ["2.0.0", "1.10.0"])

    def test_biocontainers_build_suffix(self):
        newer = fc.find_newer_tags(
            "0.23.4--h5f740d0_0",
            ["0.23.4--h5f740d0_0", "0.23.4--h5f740d0_1", "0.24.0--abc_0"],
        )
        assert "0.24.0--abc_0" in newer

    def test_empty_when_only_older(self):
        assert fc.find_newer_tags("3.0.0", ["2.9.9", "1.0.0"]) == []


class TestCheckToolWithMockNetwork:

    def _write_tool(self, tmp_path: Path, image: str) -> Path:
        p = tmp_path / "tool.yaml"
        p.write_text(
            f"id: t\nversion: '1.0.0'\ncontainer:\n  image: {image}\n",
            encoding="utf-8",
        )
        return p

    def test_update_available(self, tmp_path):
        p = self._write_tool(tmp_path, "staphb/spades:4.0.0")
        with patch.object(fc, "fetch_tags", return_value=["4.1.0", "4.0.0"]):
            rec = fc.check_tool(p)
        assert rec["status"] == "update_available"
        assert "4.1.0" in rec["newer_tags"]

    def test_yanked(self, tmp_path):
        p = self._write_tool(tmp_path, "staphb/spades:4.0.0")
        import urllib.error
        def boom(*a, **kw):
            raise urllib.error.HTTPError("u", 404, "gone", None, None)
        with patch.object(fc, "fetch_tags", side_effect=boom):
            rec = fc.check_tool(p)
        assert rec["status"] == "yanked"

    def test_check_failed_on_other_http_error(self, tmp_path):
        p = self._write_tool(tmp_path, "staphb/spades:4.0.0")
        import urllib.error
        def boom(*a, **kw):
            raise urllib.error.HTTPError("u", 500, "srv", None, None)
        with patch.object(fc, "fetch_tags", side_effect=boom):
            rec = fc.check_tool(p)
        assert rec["status"] == "check_failed"

    def test_ok_when_current_in_tags_and_no_newer(self, tmp_path):
        p = self._write_tool(tmp_path, "staphb/spades:4.0.0")
        with patch.object(fc, "fetch_tags", return_value=["4.0.0", "3.9.0"]):
            rec = fc.check_tool(p)
        assert rec["status"] == "ok"
        assert rec["newer_tags"] == []


class TestRenderReport:

    def test_includes_each_section(self):
        records = [
            {"tool_id": "a", "version": "1", "image": "x:1",
             "status": "update_available", "newer_tags": ["1.1"], "note": ""},
            {"tool_id": "b", "version": "2", "image": "y:2",
             "status": "yanked", "newer_tags": [], "note": "gone"},
        ]
        out = fc.render_report(records, cowork_pulse=10)
        assert "Newer tags available (1)" in out
        assert "Yanked / image not found (1)" in out
        assert "10 days ago" in out

    def test_cowork_silence_warning(self):
        out = fc.render_report([], cowork_pulse=None)
        assert "no candidate YAMLs found" in out

    def test_cowork_overdue_warning(self):
        out = fc.render_report([], cowork_pulse=60)
        assert "60 days ago" in out
        assert "Investigate" in out

    def test_t3_silence_warning(self):
        out = fc.render_report([], cowork_pulse=5, t3_pulse=None)
        assert "T3 local cron" in out
        assert "never run" in out

    def test_t3_overdue_warning(self):
        out = fc.render_report([], cowork_pulse=5, t3_pulse=50)
        assert "T3 local cron: last ran **50 days ago**" in out


class TestDaysSinceLastCandidate:

    def test_none_when_dir_missing(self, tmp_path):
        assert fc.days_since_last_candidate(tmp_path / "nope") is None

    def test_none_when_empty(self, tmp_path):
        (tmp_path / "candidates").mkdir()
        assert fc.days_since_last_candidate(tmp_path / "candidates") is None

    def test_returns_int(self, tmp_path):
        d = tmp_path / "candidates" / "2026-05"
        d.mkdir(parents=True)
        (d / "x.yaml").write_text("id: x", encoding="utf-8")
        n = fc.days_since_last_candidate(tmp_path / "candidates")
        assert isinstance(n, int) and n >= 0


class TestExitCodes:

    def test_returns_zero_when_all_ok(self, tmp_path, monkeypatch):
        reg = tmp_path / "registry" / "tools" / "qc"
        reg.mkdir(parents=True)
        (reg / "t.yaml").write_text(
            "id: t\nversion: '1.0.0'\ncontainer:\n  image: staphb/spades:4.0.0\n",
            encoding="utf-8",
        )
        with patch.object(fc, "fetch_tags", return_value=["4.0.0"]):
            rc = fc.main([
                "--registry", str(reg),
                "--candidates-dir", str(tmp_path / "nope"),
                "--out", str(tmp_path / "r.md"),
            ])
        assert rc == 0
        assert (tmp_path / "r.md").exists()

    def test_returns_two_on_yanked(self, tmp_path, monkeypatch):
        import urllib.error
        reg = tmp_path / "registry" / "tools" / "qc"
        reg.mkdir(parents=True)
        (reg / "t.yaml").write_text(
            "id: t\nversion: '1.0.0'\ncontainer:\n  image: staphb/spades:4.0.0\n",
            encoding="utf-8",
        )
        def boom(*a, **kw):
            raise urllib.error.HTTPError("u", 404, "gone", None, None)
        with patch.object(fc, "fetch_tags", side_effect=boom):
            rc = fc.main([
                "--registry", str(reg),
                "--candidates-dir", str(tmp_path / "nope"),
                "--out", str(tmp_path / "r.md"),
            ])
        assert rc == 2
