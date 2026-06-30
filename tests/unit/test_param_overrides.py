"""Unit tests for `--set` stage-parameter overrides.

These exercise the SDK engine with a MockBackend (no Docker): an override
must reach the rendered command, respect scope precedence, be safe against
positional args, and land in the cache key (so a cached default can't mask it).
"""
from __future__ import annotations

import pytest

from bioflow import stage
from bioflow.sdk import MockBackend, set_backend, set_param_overrides, set_workspace


@pytest.fixture
def mock_env(tmp_path):
    set_workspace(tmp_path)
    mb = MockBackend()
    set_backend(mb)
    set_param_overrides({})          # start clean
    try:
        yield mb
    finally:
        set_param_overrides({})      # never leak overrides into other tests


def _tunable_stage(cache: bool = False):
    @stage(image="img:1", cache=cache)
    def mystage(x, *, out_dir, kmer: str = "auto", qual: int = 15):
        return f"tool -k {kmer} -q {qual} {x}"
    return mystage


def test_stage_scoped_override_reaches_command(mock_env):
    s = _tunable_stage()
    set_param_overrides({"mystage.kmer": "21,33,55"})
    s("in.fq")
    cmd = mock_env.calls[0]["command"]
    assert "-k 21,33,55" in cmd
    assert "-q 15" in cmd            # untouched default stays


def test_bare_param_override_and_int_coercion(mock_env):
    s = _tunable_stage()
    set_param_overrides({"qual": "30"})   # bare name → any stage with that param
    s("in.fq")
    assert "-q 30" in mock_env.calls[0]["command"]


def test_stage_scope_beats_bare(mock_env):
    s = _tunable_stage()
    set_param_overrides({"kmer": "11", "mystage.kmer": "99"})
    s("in.fq")
    assert "-k 99" in mock_env.calls[0]["command"]


def test_positional_and_unknown_params_are_safe(mock_env):
    s = _tunable_stage()
    # 'x' is positional (not keyword-only) → must NOT be overridable;
    # 'nope' matches no parameter → silently ignored (no crash).
    set_param_overrides({"mystage.x": "HACKED", "nope": "1"})
    s("in.fq")
    cmd = mock_env.calls[0]["command"]
    assert "in.fq" in cmd and "HACKED" not in cmd


def test_override_is_in_cache_key(mock_env):
    """A changed override must force a re-run, not hit the default's cache."""
    s = _tunable_stage(cache=True)
    s("in")                                   # run 1 — default kmer=auto
    set_param_overrides({"mystage.kmer": "21"})
    s("in")                                   # run 2 — override → cache miss
    assert len(mock_env.calls) == 2
    assert "-k auto" in mock_env.calls[0]["command"]
    assert "-k 21" in mock_env.calls[1]["command"]


def test_same_override_hits_cache(mock_env):
    """Identical override on identical inputs should reuse the cache."""
    set_param_overrides({"mystage.kmer": "21"})
    s = _tunable_stage(cache=True)
    s("in")
    s("in")                                   # same key → cache hit, no 2nd call
    assert len(mock_env.calls) == 1
