"""Phase 2H — container log streaming tests."""
from __future__ import annotations

import logging

import pytest

from bioflow import (
    stage,
    set_workspace,
    set_backend,
    set_log_streaming,
    is_log_streaming_enabled,
    MockBackend,
)
from bioflow.core.runner import CommandResult


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    set_backend(MockBackend())
    set_log_streaming(False)
    yield
    set_log_streaming(False)


# ---------------------------------------------------------------------------
# Toggle behaviour
# ---------------------------------------------------------------------------

class TestToggle:

    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("BIOFLOW_STREAM_LOGS", raising=False)
        assert is_log_streaming_enabled() is False

    def test_explicit_on(self):
        set_log_streaming(True)
        assert is_log_streaming_enabled() is True

    def test_env_var_turns_on(self, monkeypatch):
        set_log_streaming(False)
        monkeypatch.setenv("BIOFLOW_STREAM_LOGS", "1")
        assert is_log_streaming_enabled() is True

    def test_env_var_accepts_true_yes(self, monkeypatch):
        set_log_streaming(False)
        monkeypatch.setenv("BIOFLOW_STREAM_LOGS", "true")
        assert is_log_streaming_enabled() is True
        monkeypatch.setenv("BIOFLOW_STREAM_LOGS", "yes")
        assert is_log_streaming_enabled() is True


# ---------------------------------------------------------------------------
# Plumbing through to the backend
# ---------------------------------------------------------------------------

class TestBackendPlumbing:

    def _streaming_backend(self):
        """Backend that records whether log_callback was passed."""
        class Streaming:
            _STREAMING_SUPPORTED = True
            def __init__(self):
                self.received_callback = False
                self.callback = None
                self.calls = []
            def run(self, *, log_callback=None, **kw):
                self.received_callback = log_callback is not None
                self.callback = log_callback
                self.calls.append(kw)
                # Exercise the callback to confirm it's wired through
                if log_callback:
                    log_callback("hello from container")
                return CommandResult(exit_code=0)
        return Streaming()

    def test_no_callback_when_streaming_off(self):
        be = self._streaming_backend()
        set_backend(be)
        set_log_streaming(False)

        @stage(image="x:1", cache=False)
        def s(x): return f"echo {x}"
        s("a")
        assert be.received_callback is False

    def test_callback_wired_when_streaming_on(self):
        be = self._streaming_backend()
        set_backend(be)
        set_log_streaming(True)

        @stage(image="x:1", cache=False)
        def s(x): return f"echo {x}"
        s("a")
        assert be.received_callback is True

    def test_callback_prefixes_with_stage_name(self, caplog):
        be = self._streaming_backend()
        set_backend(be)
        set_log_streaming(True)

        @stage(image="x:1", cache=False)
        def my_stage_name(x): return f"echo {x}"

        with caplog.at_level(logging.INFO, logger="bioflow"):
            my_stage_name("a")
        # Container output forwarded with stage prefix
        assert any(
            "[my_stage_name] hello from container" in r.message
            for r in caplog.records
        )

    def test_mock_backend_unaffected(self):
        # MockBackend doesn't declare _STREAMING_SUPPORTED.  Even when
        # streaming is ON, the SDK must NOT pass log_callback to it
        # (because MockBackend.run signature doesn't accept that kwarg).
        be = MockBackend()
        set_backend(be)
        set_log_streaming(True)

        @stage(image="x:1", cache=False)
        def s(x): return f"echo {x}"

        # Must not raise even though streaming is enabled
        result = s("a")
        assert result.ok
