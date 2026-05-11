"""LLM L6 — audit log + daily cost cap tests."""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bioflow.llm import audit as _audit
from bioflow.llm import CapExceeded


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    # Redirect the audit log to a temp file per test
    monkeypatch.setattr(_audit, "AUDIT_PATH", tmp_path / "audit.log")
    # And ensure no cap is set by default
    monkeypatch.delenv("BIOFLOW_LLM_DAILY_CAP_USD", raising=False)
    yield tmp_path / "audit.log"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

class TestEstimateCost:

    def test_ollama_is_free(self):
        assert _audit.estimate_cost("ollama", "qwen2.5-coder:7b", 1000, 1000) == 0.0

    def test_disabled_is_free(self):
        assert _audit.estimate_cost("disabled", "", 0, 0) == 0.0

    def test_haiku_pricing(self):
        cost = _audit.estimate_cost(
            "anthropic", "claude-3-5-haiku-latest", 1_000_000, 0,
        )
        # 1 MTok input @ $1.00 = exactly $1
        assert cost == pytest.approx(1.0, rel=1e-6)

    def test_haiku_pricing_output(self):
        cost = _audit.estimate_cost(
            "anthropic", "claude-3-5-haiku-latest", 0, 1_000_000,
        )
        # 1 MTok output @ $5.00 = exactly $5
        assert cost == pytest.approx(5.0, rel=1e-6)

    def test_unknown_model_returns_none(self):
        assert _audit.estimate_cost(
            "anthropic", "totally-made-up-model", 1000, 1000,
        ) is None


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

class TestRecord:

    def test_writes_jsonl(self, _isolated_audit):
        _audit.record(
            action="explain", backend="anthropic",
            model="claude-3-5-haiku-latest",
            input_tokens=100, output_tokens=200,
            cost_usd=0.001,
            redacted_prompt="Term: x\nContext: y",
        )
        text = _isolated_audit.read_text(encoding="utf-8")
        assert text.endswith("\n")
        entry = json.loads(text.strip())
        assert entry["action"] == "explain"
        assert entry["input_tokens"] == 100
        assert entry["cost_usd"] == 0.001

    def test_multiple_entries_appended(self, _isolated_audit):
        for i in range(3):
            _audit.record(
                action="explain", backend="anthropic", model="x",
                input_tokens=i, output_tokens=i, cost_usd=0.0,
            )
        entries = _audit.read_entries()
        assert len(entries) == 3
        assert [e["input_tokens"] for e in entries] == [0, 1, 2]

    def test_long_prompt_truncated(self, _isolated_audit):
        _audit.record(
            action="x", backend="anthropic", model="x",
            input_tokens=0, output_tokens=0, cost_usd=0.0,
            redacted_prompt="A" * 5000,
        )
        entry = _audit.read_entries()[0]
        assert "<trunc>" in entry["redacted_prompt"]
        assert len(entry["redacted_prompt"]) < 1000

    def test_write_failure_does_not_raise(self, monkeypatch, tmp_path):
        # Force AUDIT_PATH to an undeletable directory to trigger OSError
        bad = tmp_path / "nope" / "x.log"
        monkeypatch.setattr(_audit, "AUDIT_PATH", bad)
        def boom(*args, **kwargs):
            raise OSError("simulated permission failure")
        monkeypatch.setattr(Path, "mkdir", boom)
        # Should NOT raise — audit must never break the user's analysis
        _audit.record(action="x", backend="ollama", model="y")


# ---------------------------------------------------------------------------
# today_total_usd
# ---------------------------------------------------------------------------

class TestTodayTotal:

    def test_empty_returns_zero(self):
        assert _audit.today_total_usd() == 0.0

    def test_sums_today_only(self, _isolated_audit):
        today_iso = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        yesterday_iso = (_dt.datetime.now(_dt.timezone.utc).date()
                         - _dt.timedelta(days=1)).isoformat()
        with _isolated_audit.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": f"{today_iso}T12:00:00+00:00", "cost_usd": 0.10}) + "\n")
            fh.write(json.dumps({"ts": f"{today_iso}T13:00:00+00:00", "cost_usd": 0.20}) + "\n")
            fh.write(json.dumps({"ts": f"{yesterday_iso}T12:00:00+00:00", "cost_usd": 5.00}) + "\n")
        # 0.10 + 0.20 = 0.30, yesterday's $5 excluded
        assert _audit.today_total_usd() == pytest.approx(0.30)

    def test_none_costs_ignored(self, _isolated_audit):
        today_iso = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        with _isolated_audit.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": f"{today_iso}T01:00:00+00:00", "cost_usd": None}) + "\n")
            fh.write(json.dumps({"ts": f"{today_iso}T02:00:00+00:00", "cost_usd": 0.05}) + "\n")
        assert _audit.today_total_usd() == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# check_cap
# ---------------------------------------------------------------------------

class TestCheckCap:

    def test_no_cap_set_no_op(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_LLM_DAILY_CAP_USD", raising=False)
        # Should never raise
        _audit.check_cap(100.0)

    def test_env_var_cap_enforced(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_DAILY_CAP_USD", "1.00")
        with pytest.raises(CapExceeded, match="exceeded"):
            _audit.check_cap(2.0)

    def test_under_cap_passes(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_DAILY_CAP_USD", "5.00")
        # No spend yet + $1 fresh call → OK
        _audit.check_cap(1.0)

    def test_zero_cost_calls_always_pass(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_DAILY_CAP_USD", "0.01")
        # Ollama calls are $0 — never blocked
        _audit.check_cap(0.0)

    def test_accumulated_today_counts(self, _isolated_audit, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_DAILY_CAP_USD", "1.00")
        today_iso = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        with _isolated_audit.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": f"{today_iso}T01:00:00+00:00", "cost_usd": 0.80}) + "\n")
        # Already spent 0.80 — a 0.30 call should be rejected (would total 1.10)
        with pytest.raises(CapExceeded):
            _audit.check_cap(0.30)
        # But a 0.10 call still fits (would total 0.90)
        _audit.check_cap(0.10)


# ---------------------------------------------------------------------------
# Wired into the LLM dispatch
# ---------------------------------------------------------------------------

class TestIntegrationWithBackends:

    def test_anthropic_call_records_entry(
        self, _isolated_audit, monkeypatch,
    ):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

        # Stub anthropic returning usage block too
        fake_msg = MagicMock()
        fake_msg.content = [MagicMock(text="answer")]
        fake_msg.usage = MagicMock(input_tokens=120, output_tokens=80)

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            from bioflow.llm import explain
            explain("x", backend="anthropic")

        entries = _audit.read_entries()
        assert len(entries) >= 1
        latest = entries[-1]
        assert latest["backend"] == "anthropic"
        assert latest["input_tokens"] == 120
        assert latest["output_tokens"] == 80
        # Haiku pricing: (120 * 1.00 + 80 * 5.00) / 1e6 = 0.00052
        assert latest["cost_usd"] == pytest.approx(0.00052, rel=1e-3)

    def test_cap_blocks_anthropic_call_before_send(
        self, _isolated_audit, monkeypatch,
    ):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        # Tiny cap — even a small prompt's worst-case cost should hit it
        monkeypatch.setenv("BIOFLOW_LLM_DAILY_CAP_USD", "0.000001")

        fake_client = MagicMock()
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))
        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            from bioflow.llm import explain
            with pytest.raises(CapExceeded):
                explain("anything", backend="anthropic")

        # The model was NEVER invoked (cap caught it before .create())
        fake_client.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCli:

    def _run(self, argv):
        from typer.testing import CliRunner
        from bioflow.cli import app
        return CliRunner().invoke(app, argv)

    def test_audit_no_history_yellow(self, _isolated_audit, monkeypatch):
        monkeypatch.setattr(_audit, "AUDIT_PATH", _isolated_audit)
        r = self._run(["llm", "audit"])
        assert r.exit_code == 0
        assert "No LLM calls" in r.stdout

    def test_audit_shows_entries(self, _isolated_audit, monkeypatch):
        _audit.record(
            action="explain", backend="anthropic",
            model="claude-3-5-haiku-latest",
            input_tokens=100, output_tokens=50, cost_usd=0.0003,
        )
        r = self._run(["llm", "audit"])
        assert r.exit_code == 0
        assert "explain" in r.stdout
        assert "anthropic" in r.stdout
