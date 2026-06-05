"""Unit tests for the `bioflow doctor` host self-check."""
from __future__ import annotations

import json
import subprocess

from bioflow.core import doctor
from bioflow.core.doctor import (
    CheckResult,
    exit_code,
    run_checks,
    summarize,
)


# ---------------------------------------------------------------------------
# Pure check functions
# ---------------------------------------------------------------------------

class TestIndividualChecks:

    def test_python_ok_on_current_runtime(self):
        r = doctor._check_python()
        # Tests run on the same interpreter, which the project supports.
        assert r.status == "ok"
        assert r.name == "python"
        assert "version" in r.detail

    def test_arch_classifies_known_machines(self):
        r = doctor._check_arch()
        # Local machine must be one of the canonical arches OR a warn.
        assert r.status in ("ok", "warn")
        assert r.name == "arch"

    def test_docker_cli_missing(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
        r = doctor._check_docker_cli()
        assert r.status == "fail"
        assert r.fix and "Install Docker" in r.fix

    def test_docker_cli_present(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _: "/fake/docker")
        r = doctor._check_docker_cli()
        assert r.status == "ok"
        assert r.detail["path"] == "/fake/docker"

    def test_docker_daemon_unreachable(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _: "/fake/docker")

        def fake_run(*_args, **_kwargs):
            return subprocess.CompletedProcess(
                args=["docker", "info"],
                returncode=1,
                stdout="",
                stderr="Cannot connect to the Docker daemon",
            )

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)
        r = doctor._check_docker_daemon()
        assert r.status == "fail"
        assert "Cannot connect" in r.message

    def test_docker_daemon_no_cli(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
        r = doctor._check_docker_daemon()
        assert r.status == "fail"
        assert "docker_cli" in (r.fix or "")

    def test_docker_daemon_reachable(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda _: "/fake/docker")

        def fake_run(*_args, **_kwargs):
            return subprocess.CompletedProcess(
                args=["docker", "info"],
                returncode=0,
                stdout="24.0.7\n",
                stderr="",
            )

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)
        r = doctor._check_docker_daemon()
        assert r.status == "ok"
        assert r.detail["server_version"] == "24.0.7"

    def test_docker_socket_on_windows_is_ok(self, monkeypatch):
        monkeypatch.setattr(doctor.platform, "system", lambda: "Windows")
        r = doctor._check_docker_socket()
        assert r.status == "ok"
        assert "pipe" in r.message.lower()

    def test_cpu_low_warns(self, monkeypatch):
        import psutil

        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 2)
        r = doctor._check_cpu()
        assert r.status == "warn"
        assert r.detail["cpu_count"] == 2

    def test_cpu_zero_fails(self, monkeypatch):
        import psutil

        monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 1)
        r = doctor._check_cpu()
        assert r.status == "fail"

    def test_ram_below_minimum_fails(self, monkeypatch):
        import psutil

        class _Mem:
            total = int(2 * 1024**3)  # 2 GB

        monkeypatch.setattr(psutil, "virtual_memory", lambda: _Mem())
        r = doctor._check_ram()
        assert r.status == "fail"

    def test_ram_between_min_and_warn_warns(self, monkeypatch):
        import psutil

        class _Mem:
            total = int(6 * 1024**3)  # 6 GB

        monkeypatch.setattr(psutil, "virtual_memory", lambda: _Mem())
        r = doctor._check_ram()
        assert r.status == "warn"

    def test_disk_below_min_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            doctor.shutil,
            "disk_usage",
            lambda _p: type("U", (), {"total": 0, "used": 0, "free": 1 * 1024**3})(),
        )
        r = doctor._check_disk(tmp_path)
        assert r.status == "fail"
        assert "free" in r.message

    def test_disk_warn_band(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            doctor.shutil,
            "disk_usage",
            lambda _p: type("U", (), {"total": 0, "used": 0, "free": 30 * 1024**3})(),
        )
        r = doctor._check_disk(tmp_path)
        assert r.status == "warn"

    def test_disk_ample(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            doctor.shutil,
            "disk_usage",
            lambda _p: type("U", (), {"total": 0, "used": 0, "free": 200 * 1024**3})(),
        )
        r = doctor._check_disk(tmp_path)
        assert r.status == "ok"

    def test_writable_path(self, tmp_path):
        r = doctor._check_writable("workspace", tmp_path, severity_on_fail="fail")
        assert r.status == "ok"

    def test_writable_creates_missing(self, tmp_path):
        target = tmp_path / "fresh"
        assert not target.exists()
        r = doctor._check_writable("workspace", target, severity_on_fail="fail")
        assert r.status == "ok"
        assert target.is_dir()

    def test_registry_loads(self, tmp_path):
        # default_registry_dir resolves to ./registry or the bundled copy.
        r = doctor._check_registry()
        assert r.status == "ok"
        assert r.detail["tool_count"] > 0

    def test_registry_missing_tools_dir(self, tmp_path):
        # Empty path -> no tools/ subdir -> fail.
        r = doctor._check_registry(registry_dir=tmp_path)
        assert r.status == "fail"
        assert "missing tools/" in r.message


# ---------------------------------------------------------------------------
# Aggregate behaviour
# ---------------------------------------------------------------------------

class TestRunChecks:

    def test_returns_at_least_all_declared_checks(self, tmp_path):
        results = run_checks(workspace=tmp_path)
        names = {r.name for r in results}
        expected = {
            "python", "arch", "docker_cli", "docker_daemon",
            "docker_socket", "cpu", "ram", "disk", "gpu",
            "registry", "home_config", "workspace",
        }
        assert expected.issubset(names)

    def test_no_check_raises_even_with_broken_workspace(self, monkeypatch, tmp_path):
        # Force the disk check to blow up — run_checks should still return
        # one CheckResult per check and surface the failure.
        def boom(_p):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(doctor.shutil, "disk_usage", boom)
        results = run_checks(workspace=tmp_path)
        disk = next(r for r in results if r.name == "disk")
        assert disk.status == "fail"

    def test_summarize_counts_buckets(self):
        results = [
            CheckResult("a", "ok", "fine"),
            CheckResult("b", "warn", "meh"),
            CheckResult("c", "warn", "meh"),
            CheckResult("d", "fail", "broken"),
        ]
        s = summarize(results)
        assert s == {"ok": 1, "warn": 2, "fail": 1}

    def test_exit_code_zero_when_no_fail(self):
        assert exit_code([
            CheckResult("a", "ok", "fine"),
            CheckResult("b", "warn", "meh"),
        ]) == 0

    def test_exit_code_nonzero_on_any_fail(self):
        assert exit_code([
            CheckResult("a", "ok", "fine"),
            CheckResult("b", "fail", "broken"),
        ]) == 1


# ---------------------------------------------------------------------------
# CLI integration — `bioflow doctor`
# ---------------------------------------------------------------------------

def _invoke(argv):
    from typer.testing import CliRunner

    from bioflow.cli import app

    return CliRunner().invoke(app, argv)


class TestDoctorCli:

    def test_json_output_is_parseable(self, tmp_path):
        result = _invoke([
            "doctor", "--json", "--workspace", str(tmp_path),
        ])
        # Exit code is 0 or 1 depending on host — both are legal outcomes.
        assert result.exit_code in (0, 1)
        # In CliRunner, sys.stdout from doctor lands in result.stdout.
        # The JSON portion is whatever survives Rich-free writes.
        payload = json.loads(result.stdout)
        assert "summary" in payload
        assert "checks" in payload
        assert isinstance(payload["checks"], list)
        assert payload["checks"], "expected at least one check"
        # Every check carries the required fields.
        for c in payload["checks"]:
            assert {"name", "status", "message"}.issubset(c.keys())
            assert c["status"] in ("ok", "warn", "fail")

    def test_human_output_lists_each_check(self, tmp_path):
        result = _invoke([
            "doctor", "--workspace", str(tmp_path),
        ])
        # exit code is allowed to be 0 or 1
        assert result.exit_code in (0, 1)
        # Each check name must appear in the rendered output.
        for name in ("python", "registry", "workspace"):
            assert name in result.stdout
