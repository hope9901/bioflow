"""`bioflow update auto` — scheduled-pipeline mode tests.

Verifies the CLI walks candidate dirs, writes a JSON report, and obeys
--auto-approve / --dry-run.  Uses MockBackend so no Docker is touched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


VALID_CANDIDATE_YAML = """\
id: dummy_tool_xyz
name: DummyTool
version: "1.0.0"
category: qc
stage: [genome_assembly.step1]
input_types: [fastq_short_paired]
output_types: [qc_html]
applicable:
  species: [any]
  read_type: [short]
  mode: [any]
container:
  image: busybox:latest
  pull_policy: if_not_present
resources:
  min:         { cpu: 1, ram_gb: 1, disk_gb: 1 }
  recommended: { cpu: 1, ram_gb: 1, disk_gb: 1 }
  gpu: false
  arch: [x86_64]
command_template: |
  echo dummy
citation: "test"
added: "2026-05-11"
last_reviewed: "2026-05-11"
update_meta:
  month: "2026-05"
"""


def _run(argv, cwd=None):
    """Invoke the CLI with the given args."""
    from typer.testing import CliRunner
    from bioflow.cli import app
    return CliRunner().invoke(app, argv)


class TestNoCandidates:

    def test_empty_candidates_dir_exits_zero(self, tmp_path, monkeypatch):
        cands = tmp_path / "candidates"
        cands.mkdir()
        monkeypatch.chdir(tmp_path)
        r = _run([
            "update", "auto",
            "--candidates-dir", str(cands),
        ])
        assert r.exit_code == 0
        assert "No candidate YAML files" in r.stdout


class TestReportWritten:

    def _set_up_candidate(self, tmp_path):
        cand_dir = tmp_path / "candidates" / "2026-05"
        cand_dir.mkdir(parents=True)
        yaml_path = cand_dir / "dummy.yaml"
        yaml_path.write_text(VALID_CANDIDATE_YAML, encoding="utf-8")
        return cand_dir, yaml_path

    def test_report_json_emitted(self, tmp_path, monkeypatch):
        cand_dir, yaml_path = self._set_up_candidate(tmp_path)
        report = tmp_path / "report.json"
        monkeypatch.chdir(tmp_path)
        r = _run([
            "update", "auto",
            "--candidates-dir", str(cand_dir),
            "--report", str(report),
        ])
        # Exit code may be 1 if benchmark fails (no test dataset for our
        # fake stage), but the report must still land
        assert report.exists()
        data = json.loads(report.read_text(encoding="utf-8"))
        assert "ran_at" in data
        assert data["candidates_scanned"] == 1
        assert data["auto_approve"] is False
        assert data["real_docker"] is False
        assert isinstance(data["results"], list)
        assert data["results"][0]["candidate"].endswith("dummy.yaml")


class TestAutoApproveFlag:

    def test_auto_approve_off_by_default(self, tmp_path, monkeypatch):
        """The default is 'safe' — benchmark only, never promote."""
        cands = tmp_path / "candidates"
        cands.mkdir()
        (cands / "x.yaml").write_text(VALID_CANDIDATE_YAML, encoding="utf-8")
        # No --auto-approve flag → report should still record auto_approve=False
        report = tmp_path / "r.json"
        monkeypatch.chdir(tmp_path)
        _run([
            "update", "auto",
            "--candidates-dir", str(cands),
            "--report", str(report),
        ])
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["auto_approve"] is False


class TestGitPushMaintainerMode:
    """`--git-commit` / `--git-push` are off by default and only the
    maintainer should turn them on.  They're plumbed through subprocess
    so we mock the git binary; tests must NOT touch the real .git."""

    def test_git_flags_off_by_default(self, tmp_path, monkeypatch):
        """No --git-commit ⇒ subprocess.run is never invoked."""
        from unittest.mock import patch
        cand_dir = tmp_path / "candidates"
        cand_dir.mkdir()
        (cand_dir / "x.yaml").write_text(VALID_CANDIDATE_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with patch("subprocess.run") as fake_run:
            _run([
                "update", "auto",
                "--candidates-dir", str(cand_dir),
                "--report", str(tmp_path / "r.json"),
            ])
        fake_run.assert_not_called()

    def test_git_commit_invokes_git_add_and_commit(
        self, tmp_path, monkeypatch,
    ):
        from unittest.mock import patch, MagicMock
        cand_dir = tmp_path / "candidates"
        cand_dir.mkdir()
        (cand_dir / "x.yaml").write_text(VALID_CANDIDATE_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        # Stub git: `git diff --cached --quiet` returns 1 (changes present)
        def fake_git(argv, **kwargs):
            ret = MagicMock(returncode=0, stdout="", stderr="")
            if "diff" in argv:
                ret.returncode = 1     # 1 = there ARE staged changes
            return ret
        with patch("subprocess.run", side_effect=fake_git) as fake_run:
            _run([
                "update", "auto",
                "--candidates-dir", str(cand_dir),
                "--report", str(tmp_path / "r.json"),
                "--git-commit",
            ])
        # We expect at minimum: git add, git diff --cached --quiet, git commit
        called_with = [c.args[0] for c in fake_run.call_args_list]
        assert any("add" in a for a in called_with), called_with
        assert any("commit" in a for a in called_with), called_with
        # NEVER called push because --git-push wasn't set
        assert not any("push" in a for a in called_with), called_with

    def test_git_push_implies_push(self, tmp_path, monkeypatch):
        from unittest.mock import patch, MagicMock
        cand_dir = tmp_path / "candidates"
        cand_dir.mkdir()
        (cand_dir / "x.yaml").write_text(VALID_CANDIDATE_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        def fake_git(argv, **kwargs):
            ret = MagicMock(returncode=0, stdout="main\n", stderr="")
            if "diff" in argv:
                ret.returncode = 1
            return ret
        with patch("subprocess.run", side_effect=fake_git) as fake_run:
            _run([
                "update", "auto",
                "--candidates-dir", str(cand_dir),
                "--report", str(tmp_path / "r.json"),
                "--git-push",
            ])
        called_with = [c.args[0] for c in fake_run.call_args_list]
        assert any("push" in a for a in called_with), called_with

    def test_git_commit_skipped_when_nothing_staged(
        self, tmp_path, monkeypatch,
    ):
        from unittest.mock import patch, MagicMock
        cand_dir = tmp_path / "candidates"
        cand_dir.mkdir()
        (cand_dir / "x.yaml").write_text(VALID_CANDIDATE_YAML, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        # Stub git: diff --cached --quiet returns 0 (no changes)
        def fake_git(argv, **kwargs):
            return MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", side_effect=fake_git) as fake_run:
            _run([
                "update", "auto",
                "--candidates-dir", str(cand_dir),
                "--report", str(tmp_path / "r.json"),
                "--git-commit",
            ])
        called_with = [c.args[0] for c in fake_run.call_args_list]
        # add + diff should be called, but commit should NOT (nothing staged)
        assert any("add" in a for a in called_with), called_with
        assert any("diff" in a for a in called_with), called_with
        assert not any("commit" in a for a in called_with), called_with


class TestUnknownAction:

    def test_unknown_action_rejected(self):
        r = _run(["update", "frobnicate"])
        assert r.exit_code != 0
        assert "Unknown action" in r.stdout
        # The help text now lists both approve and auto
        assert "auto" in r.stdout


class TestSchedulerHelpers:
    """The installer scripts ship in repo; verify they're present."""

    def test_windows_script_exists(self):
        p = Path(__file__).resolve().parents[2] / "scripts" / \
            "install-schedule-windows.ps1"
        assert p.exists(), f"Missing helper script: {p}"
        text = p.read_text(encoding="utf-8")
        assert "bioflow-monthly-update" in text
        assert "Register-ScheduledTask" in text

    def test_cron_script_exists(self):
        p = Path(__file__).resolve().parents[2] / "scripts" / \
            "install-schedule-cron.sh"
        assert p.exists(), f"Missing helper script: {p}"
        text = p.read_text(encoding="utf-8")
        assert "bioflow-monthly-update" in text
        assert "crontab" in text
