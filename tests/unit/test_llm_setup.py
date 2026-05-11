"""LLM L3/L4 + first-time setup wizard tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bioflow.llm import (
    recommend_local_model,
    load_config,
    save_config,
    new_tool,
    suggest_command,
    LlmDisabled,
    LlmError,
    ModelRec,
)


# ---------------------------------------------------------------------------
# Hardware-based recommendation
# ---------------------------------------------------------------------------

class TestRecommendLocalModel:

    def test_high_ram_picks_14b(self):
        rec = recommend_local_model(
            ram_gb=64, gpu_present=False, cpu_count=12,
        )
        assert rec.backend == "ollama"
        assert "14b" in rec.model

    def test_sweet_spot_24gb_picks_7b(self):
        rec = recommend_local_model(
            ram_gb=32, gpu_present=False, cpu_count=8,
        )
        assert rec.backend == "ollama"
        assert "7b" in rec.model

    def test_low_ram_picks_3b(self):
        rec = recommend_local_model(
            ram_gb=16, gpu_present=False, cpu_count=4,
        )
        assert rec.backend == "ollama"
        assert "3b" in rec.model

    def test_very_low_ram_picks_1b(self):
        rec = recommend_local_model(
            ram_gb=8, gpu_present=False, cpu_count=4,
        )
        assert rec.backend == "ollama"
        assert "1b" in rec.model

    def test_tiny_machine_disables(self):
        rec = recommend_local_model(
            ram_gb=4, gpu_present=False, cpu_count=2,
        )
        assert rec.backend == "disabled"
        assert rec.ollama_pull_cmd is None

    def test_gpu_bonus_promotes_tier(self):
        # 16 GB RAM alone → 3B model
        no_gpu = recommend_local_model(
            ram_gb=16, gpu_present=False, cpu_count=4,
        )
        # 16 GB RAM + GPU → effective 24 GB → 7B model
        with_gpu = recommend_local_model(
            ram_gb=16, gpu_present=True, cpu_count=4,
        )
        assert "3b" in no_gpu.model
        assert "7b" in with_gpu.model

    def test_reason_string_includes_ram(self):
        rec = recommend_local_model(
            ram_gb=32, gpu_present=False, cpu_count=8,
        )
        assert "32" in rec.reason
        assert "GB" in rec.reason

    def test_returns_modelrec_dataclass(self):
        rec = recommend_local_model(
            ram_gb=32, gpu_present=False, cpu_count=8,
        )
        assert isinstance(rec, ModelRec)


# ---------------------------------------------------------------------------
# Config file load / save
# ---------------------------------------------------------------------------

class TestConfigFile:

    def test_load_returns_empty_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))   # Windows
        import bioflow.llm as _llm
        monkeypatch.setattr(_llm, "CONFIG_PATH", tmp_path / "nope.yaml")
        assert load_config() == {}

    def test_save_then_load_round_trip(self, tmp_path, monkeypatch):
        import bioflow.llm as _llm
        monkeypatch.setattr(_llm, "CONFIG_PATH", tmp_path / "cfg.yaml")
        save_config({"backend": "ollama", "model": "qwen2.5-coder:7b"})
        loaded = load_config()
        assert loaded["backend"] == "ollama"
        assert loaded["model"] == "qwen2.5-coder:7b"

    def test_save_preserves_unrelated_top_level_keys(self, tmp_path, monkeypatch):
        import bioflow.llm as _llm
        cfg_path = tmp_path / "cfg.yaml"
        cfg_path.write_text(
            "other_section:\n  foo: 1\nllm:\n  backend: anthropic\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(_llm, "CONFIG_PATH", cfg_path)
        save_config({"backend": "ollama"})
        text = cfg_path.read_text(encoding="utf-8")
        assert "other_section" in text
        assert "foo: 1" in text

    def test_env_var_overrides_config(self, tmp_path, monkeypatch):
        import bioflow.llm as _llm
        monkeypatch.setattr(_llm, "CONFIG_PATH", tmp_path / "cfg.yaml")
        save_config({"backend": "ollama"})
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "openai")
        # The env var should win
        assert _llm._backend() == "openai"

    def test_config_used_when_env_unset(self, tmp_path, monkeypatch):
        import bioflow.llm as _llm
        monkeypatch.setattr(_llm, "CONFIG_PATH", tmp_path / "cfg.yaml")
        save_config({"backend": "ollama", "model": "qwen2.5-coder:3b"})
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        monkeypatch.delenv("BIOFLOW_LLM_MODEL", raising=False)
        assert _llm._backend() == "ollama"
        assert _llm._model_for_backend("ollama") == "qwen2.5-coder:3b"


# ---------------------------------------------------------------------------
# L3 new_tool
# ---------------------------------------------------------------------------

class TestNewTool:

    def test_disabled_default(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        with pytest.raises(LlmDisabled):
            new_tool(name="prokka", help_text="usage: ...")

    def test_empty_inputs_raise(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        with pytest.raises(LlmError, match="name is empty"):
            new_tool(name="  ", help_text="some help")
        with pytest.raises(LlmError, match="help_text is empty"):
            new_tool(name="prokka", help_text="")

    def test_returns_text_from_backend(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        captured: dict = {}
        fake_msg = MagicMock(content=[MagicMock(text="id: prokka\nname: Prokka\n…")])
        fake_client = MagicMock()
        def capture(**kw):
            captured.update(kw)
            return fake_msg
        fake_client.messages.create.side_effect = capture
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            text = new_tool(name="prokka", help_text="usage: prokka [opts]")
        assert "id: prokka" in text
        # Tool name + help text appear in the LLM call, nothing user-private
        user_msg = captured["messages"][0]["content"]
        assert "prokka" in user_msg
        assert "usage: prokka" in user_msg

    def test_long_help_truncated(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        captured: dict = {}
        fake_msg = MagicMock(content=[MagicMock(text="x")])
        fake_client = MagicMock()
        def capture(**kw):
            captured.update(kw); return fake_msg
        fake_client.messages.create.side_effect = capture
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            new_tool(name="t", help_text="x" * 20000)
        # User content is truncated to roughly 6 KB
        user_msg = captured["messages"][0]["content"]
        assert len(user_msg) < 8000


# ---------------------------------------------------------------------------
# L4 suggest_command
# ---------------------------------------------------------------------------

class TestSuggestCommand:

    def test_disabled_default(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        with pytest.raises(LlmDisabled):
            suggest_command(tool="prokka", intent="annotate")

    def test_empty_inputs_raise(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        with pytest.raises(LlmError, match="required"):
            suggest_command(tool="", intent="anything")
        with pytest.raises(LlmError, match="required"):
            suggest_command(tool="prokka", intent="")

    def test_round_trip(self, monkeypatch):
        monkeypatch.setenv("BIOFLOW_LLM_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
        fake_msg = MagicMock(content=[MagicMock(
            text="prokka --outdir {out_dir} {assembly_fasta}"
        )])
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg
        fake_anthropic = MagicMock(Anthropic=MagicMock(return_value=fake_client))

        with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
            cmd = suggest_command(
                tool="prokka", intent="annotate paired-end E. coli",
            )
        assert "prokka" in cmd
        assert "{out_dir}" in cmd


# ---------------------------------------------------------------------------
# CLI smoke for setup wizard + llm new-tool / suggest
# ---------------------------------------------------------------------------

class TestCli:

    def _run(self, argv, **kwargs):
        from typer.testing import CliRunner
        from bioflow.cli import app
        return CliRunner().invoke(app, argv, **kwargs)

    def test_setup_yes_writes_config(self, tmp_path, monkeypatch):
        import bioflow.llm as _llm
        monkeypatch.setattr(_llm, "CONFIG_PATH", tmp_path / "cfg.yaml")
        r = self._run(["setup", "--yes"])
        assert r.exit_code == 0
        assert (tmp_path / "cfg.yaml").exists()

    def test_setup_explicit_disabled(self, tmp_path, monkeypatch):
        import bioflow.llm as _llm
        monkeypatch.setattr(_llm, "CONFIG_PATH", tmp_path / "cfg.yaml")
        r = self._run(["setup", "--backend", "disabled"])
        assert r.exit_code == 0
        from bioflow.llm import load_config
        assert load_config()["backend"] == "disabled"

    def test_setup_rejects_unknown_backend(self):
        r = self._run(["setup", "--backend", "weirdmodel"])
        assert r.exit_code != 0

    def test_llm_new_tool_missing_args(self):
        r = self._run(["llm", "new-tool"])
        assert r.exit_code != 0
        assert "--tool" in r.stdout

    def test_llm_suggest_missing_args(self):
        r = self._run(["llm", "suggest"])
        assert r.exit_code != 0
        assert "--tool" in r.stdout or "--intent" in r.stdout

    def test_llm_new_tool_disabled(self, tmp_path, monkeypatch):
        # Even with --tool / --help-file given, if backend is disabled
        # the command should exit code 2 (the LlmDisabled signal)
        import bioflow.llm as _llm
        monkeypatch.setattr(_llm, "CONFIG_PATH", tmp_path / "cfg.yaml")
        monkeypatch.delenv("BIOFLOW_LLM_BACKEND", raising=False)
        help_file = tmp_path / "h.txt"
        help_file.write_text("usage: prokka [opts]", encoding="utf-8")
        r = self._run([
            "llm", "new-tool",
            "--tool", "prokka",
            "--help-file", str(help_file),
        ])
        assert r.exit_code == 2
