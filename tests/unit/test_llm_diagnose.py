"""LLM L2 — error diagnosis + redaction tests.

Privacy guard: every test verifies that no raw user path / email / IP
makes it into the user message that would be sent to a model.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bioflow.llm import (
    redact,
    diagnose_failure,
    LlmDisabled,
    LlmError,
)


# ---------------------------------------------------------------------------
# redact() — the core safety net
# ---------------------------------------------------------------------------

class TestRedact:

    def test_workspace_replaced(self):
        ws = "/data/lab/run42"
        out = redact(
            f"FATAL: cannot read {ws}/genomes/file.fna",
            workspace=ws,
        )
        assert ws not in out
        assert "<WORKSPACE>" in out

    def test_unix_user_paths_redacted(self):
        out = redact("/Users/alice/work/x")
        assert "/Users/<USER>/work/x" == out

    def test_home_user_paths_redacted(self):
        out = redact("/home/bob/data")
        assert "/home/<USER>/data" == out

    def test_windows_user_paths_redacted(self):
        out = redact(r"C:\Users\carol\Desktop\thing")
        assert "<USER>" in out
        assert "carol" not in out

    def test_email_redacted(self):
        out = redact("contact alice@example.com for help")
        assert "<EMAIL>" in out
        assert "alice@example.com" not in out

    def test_ipv4_redacted(self):
        out = redact("connecting to 192.168.1.42:8080")
        assert "<IP>" in out
        assert "192.168.1.42" not in out

    def test_long_token_redacted(self):
        token = "sk_test_" + "A" * 50
        out = redact(f"key={token}")
        assert token not in out
        assert "<TOKEN>" in out

    def test_short_strings_kept(self):
        out = redact("ok 200 done")
        assert out == "ok 200 done"

    def test_extra_patterns(self):
        import re
        out = redact(
            "patient_42 said hi",
            extra_patterns=[(re.compile(r"patient_\d+"), "<PHI>")],
        )
        assert "patient_42" not in out
        assert "<PHI>" in out

    def test_empty_input(self):
        assert redact("") == ""
        assert redact(None) == ""    # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# diagnose_failure dispatch + privacy
# ---------------------------------------------------------------------------

class TestDiagnoseDispatch:

    def test_disabled_default(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        with pytest.raises(LlmDisabled):
            diagnose_failure(
                stage_name="x", command="x", stderr="", exit_code=1,
            )

    def test_redaction_applied_before_send(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

        captured: dict = {}
        fake_msg = MagicMock(content=[MagicMock(text="suggestion")])
        fake_client = MagicMock()
        def capture(**kw):
            captured.update(kw)
            return fake_msg
        fake_client.messages.create.side_effect = capture
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            diagnose_failure(
                stage_name="prokka",
                command="/Users/alice/proj/run.sh --opt /Users/alice/data.fna",
                stderr="line one\nERROR: file at /Users/alice/missing.gff not found",
                exit_code=1,
            )

        user_msg = captured["messages"][0]["content"]
        # Personal username never reaches the LLM
        assert "alice" not in user_msg
        # Redacted markers ARE present
        assert "<USER>" in user_msg

    def test_workspace_redaction_in_prompt(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

        captured: dict = {}
        fake_msg = MagicMock(content=[MagicMock(text="ok")])
        fake_client = MagicMock()
        def capture(**kw):
            captured.update(kw); return fake_msg
        fake_client.messages.create.side_effect = capture
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        ws = "/scratch/run_2026"
        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            diagnose_failure(
                stage_name="x",
                command=f"prokka --outdir {ws}/p genome.fna",
                stderr=f"missing {ws}/p/log",
                exit_code=2,
                workspace=ws,
            )

        user_msg = captured["messages"][0]["content"]
        assert ws not in user_msg
        assert "<WORKSPACE>" in user_msg

    def test_long_stderr_truncated(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

        captured: dict = {}
        fake_msg = MagicMock(content=[MagicMock(text="ok")])
        fake_client = MagicMock()
        def capture(**kw):
            captured.update(kw); return fake_msg
        fake_client.messages.create.side_effect = capture
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        # 10 KB of stderr — should get truncated to ~2 KB tail
        big = "junk\n" * 2000
        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            diagnose_failure(
                stage_name="x", command="cmd", stderr=big, exit_code=1,
            )
        user_msg = captured["messages"][0]["content"]
        assert "<truncated>" in user_msg
        # Truncated body is far smaller than the full 10 KB input
        assert len(user_msg) < 4000

    def test_audit_log_written_when_path_given(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

        fake_msg = MagicMock(content=[MagicMock(text="here is the fix")])
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        audit = tmp_path / "audit.log"
        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            diagnose_failure(
                stage_name="prokka", command="prokka x", stderr="boom",
                exit_code=1, audit_log=audit,
            )
        text = audit.read_text(encoding="utf-8")
        assert "stage=prokka" not in text   # we don't store unredacted forms
        assert "prokka" in text             # the stage name itself, fine
        assert "here is the fix" in text


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCli:

    def _run(self, argv, **kwargs):
        from typer.testing import CliRunner
        from bioflow.cli import app
        return CliRunner().invoke(app, argv, **kwargs)

    def test_diagnose_disabled_default(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        r = self._run([
            "llm", "diagnose",
            "--stage", "prokka",
            "--command", "prokka x",
            "--exit-code", "1",
        ])
        assert r.exit_code == 2

    def test_diagnose_missing_args(self):
        r = self._run(["llm", "diagnose"])
        assert r.exit_code != 0
        assert "stage" in r.stdout.lower() or "required" in r.stdout.lower()

    def test_redact_subcommand(self):
        r = self._run(
            ["llm", "redact"],
            input="/Users/alice/x and 1.2.3.4\n",
        )
        assert r.exit_code == 0
        assert "alice" not in r.stdout
        assert "<USER>" in r.stdout
        assert "<IP>" in r.stdout
