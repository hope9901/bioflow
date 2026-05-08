"""LLM Phase 1 — terminology Q&A (`bioflow.llm.explain`).

The default backend is ``disabled`` so we test:
  - the safety default (raises LlmDisabled on a fresh process)
  - dispatch to each backend (mocked, no real API calls)
  - the prompt isolates *term* + *context* only — never analysis data
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bioflow.llm import explain, LlmDisabled, LlmError, _build_prompt


# ---------------------------------------------------------------------------
# Defaults — safety
# ---------------------------------------------------------------------------

class TestSafetyDefaults:

    def test_default_backend_is_disabled(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        with pytest.raises(LlmDisabled):
            explain("anything")

    def test_explicit_disabled_string(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "disabled")
        with pytest.raises(LlmDisabled):
            explain("anything")

    def test_empty_term_raises(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        with pytest.raises(LlmError, match="empty"):
            explain("")
        with pytest.raises(LlmError, match="empty"):
            explain("   ")

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "weirdmodel")
        with pytest.raises(LlmError, match="Unknown LLM backend"):
            explain("Bonferroni correction")


# ---------------------------------------------------------------------------
# Prompt isolation — term + context only
# ---------------------------------------------------------------------------

class TestPromptShape:

    def test_prompt_contains_term_and_context(self):
        p = _build_prompt("Bonferroni correction", "statistics")
        assert "Bonferroni correction" in p["user"]
        assert "statistics" in p["user"]

    def test_system_prompt_is_concise(self):
        p = _build_prompt("x", "y")
        # System prompt enforces output style; should not include any
        # placeholders or stray data
        assert "{" not in p["system"]
        assert "}" not in p["system"]
        assert len(p["system"]) < 500

    def test_no_path_or_data_leakage_via_term(self):
        # User passes the literal text — we don't auto-augment with file
        # paths, sample names, or anything else.  Verify the prompt body
        # is exactly what the user typed.
        sentinel_term = "<<MAGIC_TERM_42>>"
        p = _build_prompt(sentinel_term, "context_word")
        assert sentinel_term in p["user"]
        # Nothing else from the runtime environment surfaced
        assert "/Users" not in p["user"] and "/home" not in p["user"]


# ---------------------------------------------------------------------------
# Backend dispatch (mocked)
# ---------------------------------------------------------------------------

class TestAnthropicDispatch:

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LlmError, match="ANTHROPIC_API_KEY"):
            explain("Bonferroni", backend="anthropic")

    def test_calls_anthropic_sdk_when_available(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

        # Stub anthropic module
        fake_msg = MagicMock()
        fake_msg.content = [MagicMock(text="A short explanation.")]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            text = explain("Bonferroni", backend="anthropic")
        assert text == "A short explanation."

        # The user message contains the term but no path/data leakage
        called_kwargs = fake_client.messages.create.call_args.kwargs
        user_msg = called_kwargs["messages"][0]["content"]
        assert "Bonferroni" in user_msg


class TestOllamaDispatch:

    def test_unreachable_endpoint_raises(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_ENDPOINT", "http://127.0.0.1:1")
        with pytest.raises(LlmError, match="unreachable"):
            explain("anything", backend="ollama")

    def test_returns_response_field(self, monkeypatch):
        # Stub urllib.request.urlopen
        import json as _json
        from io import BytesIO

        class FakeResp:
            def read(self):
                return _json.dumps({"response": "Ollama said this."}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with patch("urllib.request.urlopen", return_value=FakeResp()):
            text = explain("anything", backend="ollama")
        assert text == "Ollama said this."


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCli:

    def _run(self, argv):
        from typer.testing import CliRunner
        from bioflow.cli import app
        return CliRunner().invoke(app, argv)

    def test_no_term_fails_cleanly(self):
        r = self._run(["llm", "explain"])
        assert r.exit_code != 0
        assert "term" in r.stdout.lower() or "required" in r.stdout.lower()

    def test_unknown_action_fails_cleanly(self):
        r = self._run(["llm", "uppercut", "thing"])
        assert r.exit_code != 0
        assert "Unknown action" in r.stdout

    def test_disabled_backend_returns_yellow_message(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        r = self._run(["llm", "explain", "Bonferroni"])
        # Exit code 2 = LlmDisabled distinguishable from generic errors
        assert r.exit_code == 2
        assert "disabled" in r.stdout.lower()
