"""Unit tests for update/release_watch.py — version comparison, candidate
file generation, state tracking.  GitHub API calls are stubbed."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "update"))

import release_watch as rw   # noqa: E402


TOOL_TEMPLATE = """\
id: dummytool
name: DummyTool
version: "1.0.0"
category: qc
stage: [genome_assembly.step1]
applicable: {{species: [any], read_type: [any], mode: [any]}}
container: {{image: staphb/dummytool:1.0.0}}
resources:
  min: {{cpu: 1, ram_gb: 1}}
  recommended: {{cpu: 1, ram_gb: 1}}
command_template: "true"
added: "2026-01-01"
last_reviewed: "2026-01-01"
source_repo: {repo}
"""


class TestIsNewer:
    def test_yes(self):
        assert rw.is_newer("1.1.0", "1.0.9")
        assert rw.is_newer("2.0.0", "1.99.99")

    def test_no(self):
        assert not rw.is_newer("1.0.0", "1.0.0")
        assert not rw.is_newer("0.9.0", "1.0.0")


class TestMakeCandidate:

    def test_bumps_version_and_image(self):
        doc = yaml.safe_load(TOOL_TEMPLATE.format(repo="x/y"))
        cand = rw.make_candidate(doc, "1.1.0", "2026-05-15")
        assert cand["version"] == "1.1.0"
        assert cand["container"]["image"] == "staphb/dummytool:1.1.0"
        assert cand["last_reviewed"] == "2026-05-15"
        assert cand["update_meta"]["source"] == "release_watch"
        assert cand["update_meta"]["previous_version"] == "1.0.0"


class TestScan:

    def _setup(self, tmp_path: Path) -> Path:
        reg = tmp_path / "registry" / "tools" / "qc"
        reg.mkdir(parents=True)
        (reg / "dummy.yaml").write_text(
            TOOL_TEMPLATE.format(repo="dummy/repo"), encoding="utf-8",
        )
        return reg

    def test_files_candidate_when_upstream_newer(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value="1.1.0"):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "filed" for a in actions)
        # Candidate YAML landed
        filed = list(cands.rglob("dummytool.yaml"))
        assert len(filed) == 1
        d = yaml.safe_load(filed[0].read_text(encoding="utf-8"))
        assert d["version"] == "1.1.0"
        # State recorded
        s = json.loads(state.read_text(encoding="utf-8"))
        assert s["dummytool"]["last_filed_version"] == "1.1.0"

    def test_up_to_date_when_upstream_equal(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value="1.0.0"):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "up_to_date" for a in actions)
        assert not list(cands.rglob("*.yaml"))

    def test_skips_already_filed(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        state.write_text(
            json.dumps({"dummytool": {"last_filed_version": "1.1.0"}}),
            encoding="utf-8",
        )
        with patch.object(rw, "latest_release_tag", return_value="1.1.0"):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "already_filed" for a in actions)
        assert not list(cands.rglob("*.yaml"))

    def test_dry_run_writes_nothing(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value="1.1.0"):
            actions = rw.scan(reg, cands, state, dry_run=True)
        assert any(a["result"] == "would_file" for a in actions)
        assert not state.exists()
        assert not list(cands.rglob("*.yaml")) if cands.exists() else True

    def test_handles_no_releases(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value=None):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "no_releases" for a in actions)

    def test_skips_tools_without_source_repo(self, tmp_path):
        reg = tmp_path / "registry" / "tools" / "qc"
        reg.mkdir(parents=True)
        # No source_repo field
        (reg / "no_src.yaml").write_text(
            "id: x\nversion: '1.0.0'\ncategory: qc\nstage: [genome_assembly.step1]\n"
            "applicable: {species: [any], read_type: [any], mode: [any]}\n"
            "container: {image: x:1}\n"
            "resources: {min: {cpu: 1, ram_gb: 1}, recommended: {cpu: 1, ram_gb: 1}}\n"
            "command_template: 'true'\nname: x\n",
            encoding="utf-8",
        )
        actions = rw.scan(
            reg, tmp_path / "candidates", tmp_path / "state.json",
            dry_run=False,
        )
        assert actions == []   # nothing checked


class TestBumpImageTag:
    def test_simple(self):
        assert rw._bump_image_tag("foo:1.0", "1.1") == "foo:1.1"

    def test_path(self):
        assert rw._bump_image_tag("a/b/c:1.0", "1.1") == "a/b/c:1.1"

    def test_no_tag_is_passthrough(self):
        assert rw._bump_image_tag("alpine", "1.1") == "alpine"
