"""Unit tests for interactive_build (Step 8 — custom mode).

questionary is mocked so no TTY is required.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest
import yaml

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class _MockAnswer:
    """Mimics the object returned by questionary.select()/text() — has .ask()."""
    def __init__(self, value: str) -> None:
        self._value = value

    def ask(self) -> str:
        return self._value


def _make_select_mock(answers: Iterator[str]):
    """Return a drop-in replacement for questionary.select that consumes *answers*."""
    def _select(_question: str, choices=None, **_kw) -> _MockAnswer:
        val = next(answers)
        return _MockAnswer(val)
    return _select


def _make_text_mock(answers: Iterator[str]):
    """Return a drop-in replacement for questionary.text that consumes *answers*."""
    def _text(_question: str, default: str = "", **_kw) -> _MockAnswer:
        val = next(answers)
        return _MockAnswer(val if val else default)
    return _text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_interactive_build_prokaryote_short_writes_yaml(tmp_path):
    """Full happy-path: prokaryote + short + de_novo → YAML saved with 5 stages."""
    import questionary  # must be importable (installed as dev dep)  # noqa: F401

    # Sequence of answers questionary will "receive":
    #   species, read_type, mode, workdir, registry_dir,
    #   step1-tool, step2-tool, step3-tool, step4-skip, step5-tool, step6-tool,
    #   inputs: sample_id, r1, r2
    # Repeat-masking tools (step4) are only applicable for eukaryote species,
    # so with prokaryote + short reads, step4 is silently skipped (no answer consumed).
    # Answer sequence: 5 meta + 5 stage selections + 3 input texts = 13 total.
    answers = iter([
        # meta (5 text/select prompts)
        "prokaryote",                  # species
        "short",                       # read_type
        "de_novo",                     # mode
        str(tmp_path / "out"),         # workdir
        str(REGISTRY_DIR),             # registry_dir
        # stage tools (step4 has no applicable tools → auto-skipped, no answer)
        "fastp",                       # step1
        "spades",                      # step2
        "quast",                       # step3
        "prokka",                      # step5  (step4 auto-skipped)
        "eggnog_mapper",               # step6
        # required inputs
        "ecoli_test",                  # sample_id
        "",                            # reference_genome (resequencing-only, optional)
        "/data/R1.fastq.gz",           # r1
        "/data/R2.fastq.gz",           # r2
        "",                            # bakta_db_dir (optional)
        "",                            # repeat_species (optional)
        "/refs/eggnog",                # eggnog_db_dir
    ])

    def select_side_effect(question, choices=None, **kw):
        return _MockAnswer(next(answers))

    def text_side_effect(question, default="", **kw):
        val = next(answers)
        return _MockAnswer(val if val else default)

    out = tmp_path / "custom.yaml"

    with (
        patch("questionary.select", side_effect=select_side_effect),
        patch("questionary.text",   side_effect=text_side_effect),
    ):
        from bioflow.core.planner import interactive_build
        interactive_build("genome_assembly", out)

    assert out.exists(), "YAML file should have been created"
    data = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert data["pipeline"] == "genome_assembly"
    assert data["species"]  == "prokaryote"
    # step4 auto-skipped (no applicable tools) → 5 active stages
    assert len(data["stages"]) == 5
    stage_tool_ids = [s["tool_id"] for s in data["stages"]]
    assert "prokka" in stage_tool_ids
    assert "spades" in stage_tool_ids


def test_interactive_build_unknown_pipeline_raises(tmp_path):
    """Passing an unrecognised pipeline name should raise ValueError immediately."""
    from bioflow.core.planner import interactive_build

    with pytest.raises(ValueError, match="Unknown pipeline"):
        interactive_build("bad_pipeline", tmp_path / "out.yaml")


def test_interactive_build_artifact_chaining(tmp_path):
    """step2 spades params should receive cleaned reads path from step1 fastp."""
    import questionary  # noqa: F401

    answers = iter([
        # meta
        "prokaryote", "short", "de_novo",
        str(tmp_path / "out"),
        str(REGISTRY_DIR),
        # stages
        "fastp",       # step1
        "spades",      # step2
        "quast",       # step3
        "__skip__",    # step4
        "prokka",      # step5
        "eggnog_mapper",  # step6
        # inputs
        "test_sample",
        "",                   # reference_genome (resequencing-only)
        "/in/R1.fastq.gz",
        "/in/R2.fastq.gz",
        "",                   # bakta_db_dir (optional)
        "",                   # repeat_species (optional)
        "/refs/eggnog",       # eggnog_db_dir
    ])

    def _sel(q, choices=None, **kw):
        return _MockAnswer(next(answers))

    def _txt(q, default="", **kw):
        val = next(answers)
        return _MockAnswer(val if val else default)

    out = tmp_path / "plan.yaml"
    with (
        patch("questionary.select", side_effect=_sel),
        patch("questionary.text",   side_effect=_txt),
    ):
        from bioflow.core.planner import interactive_build
        interactive_build("genome_assembly", out)

    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    spades_stage = next(s for s in data["stages"] if s["tool_id"] == "spades")
    expected_r1 = str(tmp_path / "out" / "genome_assembly_step1" / "clean_R1.fastq.gz")
    assert spades_stage["params"].get("r1") == expected_r1


def test_interactive_build_rnaseq_four_stages(tmp_path):
    """RNA-seq pipeline → exactly 4 stages, step2 = salmon."""
    import questionary  # noqa: F401

    answers = iter([
        # meta
        "eukaryote", "short", "de_novo",
        str(tmp_path / "out"),
        str(REGISTRY_DIR),
        # stages
        "fastp",            # rnaseq step1
        "salmon",           # rnaseq step2
        "deseq2",           # rnaseq step3
        "clusterprofiler",  # rnaseq step4
        # inputs
        "rna_test",
        "/data/samples.csv",
        "/refs/genome.fa",
        "/refs/genome.gtf",
    ])

    def _sel(q, choices=None, **kw):
        return _MockAnswer(next(answers))

    def _txt(q, default="", **kw):
        val = next(answers)
        return _MockAnswer(val if val else default)

    out = tmp_path / "rna.yaml"
    with (
        patch("questionary.select", side_effect=_sel),
        patch("questionary.text",   side_effect=_txt),
    ):
        from bioflow.core.planner import interactive_build
        interactive_build("rnaseq_deg", out)

    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["pipeline"] == "rnaseq_deg"
    assert len(data["stages"]) == 4
    assert data["stages"][1]["tool_id"] == "salmon"
