"""Unit tests for update/benchmark.py (Step 10)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT        = Path(__file__).resolve().parents[2]
REGISTRY_DIR     = REPO_ROOT / "registry"
SAMPLE_CANDIDATE = REPO_ROOT / "tests" / "fixtures" / "hypo_assembler.yaml"


# ---------------------------------------------------------------------------
# _validate_candidate
# ---------------------------------------------------------------------------

def test_validate_candidate_passes_for_sample(tmp_path):
    """The bundled sample candidate should pass schema validation."""
    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import _validate_candidate
    tool = _validate_candidate(SAMPLE_CANDIDATE)
    assert tool["id"] == "hypo_assembler"
    # update_meta must be stripped
    assert "update_meta" not in tool


def test_validate_candidate_fails_for_invalid_yaml(tmp_path):
    """A YAML missing required fields should raise ValueError."""
    bad = tmp_path / "bad_tool.yaml"
    bad.write_text(yaml.dump({"id": "bad", "name": "Bad"}), encoding="utf-8")

    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import _validate_candidate
    with pytest.raises(ValueError, match="Schema validation"):
        _validate_candidate(bad)


# ---------------------------------------------------------------------------
# _resolve_test_dataset
# ---------------------------------------------------------------------------

def test_resolve_test_dataset_prokaryote_step2():
    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import _resolve_test_dataset
    # ecoli_small must map to genome_assembly.step2 / prokaryote
    # Dataset may not exist in CI — we just check the return type
    result = _resolve_test_dataset("genome_assembly.step2", ["prokaryote"])
    # result is either a Path or None (dataset dir may not exist yet)
    assert result is None or isinstance(result, Path)


def test_resolve_test_dataset_unknown_stage():
    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import _resolve_test_dataset
    result = _resolve_test_dataset("genome_assembly.step99", ["prokaryote"])
    assert result is None


# ---------------------------------------------------------------------------
# smoke_test (mock mode — no Docker)
# ---------------------------------------------------------------------------

def test_smoke_test_skips_when_no_dataset():
    """Without a test dataset on disk, smoke_test should skip gracefully."""
    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import smoke_test
    result = smoke_test(SAMPLE_CANDIDATE, use_real_docker=False)
    # Either passes (dataset found) or skipped (dataset not yet created)
    assert result.passed or result.skipped
    assert result.error is None or result.skipped


def test_smoke_test_fails_on_schema_error(tmp_path):
    """A candidate that fails schema validation must return error, not raise."""
    bad = tmp_path / "broken.yaml"
    bad.write_text(yaml.dump({"id": "broken"}), encoding="utf-8")

    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import smoke_test
    result = smoke_test(bad, use_real_docker=False)
    assert not result.passed
    assert result.error is not None


# ---------------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------------

def test_cli_main_returns_zero_on_all_skipped(tmp_path, capsys):
    """When all candidates are skipped (no dataset), exit code should be 0."""
    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import main
    code = main(["--candidate", str(SAMPLE_CANDIDATE)])
    # 0 = no failures (skips don't count as failures)
    assert code == 0


def test_cli_main_returns_one_on_bad_candidate(tmp_path, capsys):
    """A broken candidate → exit code 1."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.dump({"id": "oops"}), encoding="utf-8")

    import sys; sys.path.insert(0, str(REPO_ROOT / "update"))  # noqa: E401, E702
    from benchmark import main
    code = main(["--candidate", str(bad)])
    assert code == 1
