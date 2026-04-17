"""E2E test: RNA-seq DEG pipeline (MockBackend).

Runs the full 4-stage rnaseq_deseq2_standard preset end-to-end.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REGISTRY_DIR  = Path(__file__).resolve().parents[2] / "registry"
TEST_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "test" / "rnaseq_toy"


def _cfg(tmp_path: Path) -> Path:
    cfg = {
        "pipeline": "rnaseq_deg",
        "species": "eukaryote",
        "read_type": "short",
        "mode": "de_novo",
        "inputs": {
            "sample_id": "rna_test",
            "sample_sheet":     str(TEST_DATA_DIR / "samples.csv"),
            "reference_genome": str(TEST_DATA_DIR / "genome.fa"),
            "annotation_gtf":   str(TEST_DATA_DIR / "genome.gtf"),
            "kegg_organism": "hsa",
        },
        "workdir": str(tmp_path / "wd"),
        "registry_dir": str(REGISTRY_DIR),
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


def test_rnaseq_four_stages_execute(tmp_path):
    """All 4 RNA-seq DEG stages must run via MockBackend."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("rnaseq_deseq2_standard", _cfg(tmp_path))
    assert len(plan.stages) == 4

    backend = MockBackend()
    run_plan(plan, backend=backend)

    assert len(backend.calls) == 4


def test_rnaseq_step2_receives_cleaned_reads(tmp_path):
    """step2 (salmon) params must contain cleaned reads path from step1 (fastp)."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("rnaseq_deseq2_standard", _cfg(tmp_path))
    run_plan(plan, backend=MockBackend())

    salmon = next(s for s in plan.stages if s.tool_id == "salmon")
    expected_r1 = str(plan.workdir / "rnaseq_deg_step1" / "clean_R1.fastq.gz")
    assert salmon.params.get("r1") == expected_r1


def test_rnaseq_checkpoint_completed(tmp_path):
    """Checkpoint must record all 4 stage IDs after a complete run."""
    from bioflow.core.checkpoint import load
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("rnaseq_deseq2_standard", _cfg(tmp_path))
    run_plan(plan, backend=MockBackend())

    state = load(plan.workdir)
    for s in plan.stages:
        assert s.stage_id in state.get("completed_stages", [])


def test_rnaseq_summary_html_generated(tmp_path):
    """pipeline_summary.html must mention rnaseq_deg and all tools."""
    from bioflow.core.planner import plan_from_preset
    from bioflow.core.report import generate_reports
    from bioflow.core.runner import MockBackend, run_plan

    plan = plan_from_preset("rnaseq_deseq2_standard", _cfg(tmp_path))
    run_plan(plan, backend=MockBackend())

    result = generate_reports(plan, tmp_path / "reports", skip_multiqc=True)
    content = result["summary"].read_text(encoding="utf-8")

    assert "rnaseq_deg" in content
    for s in plan.stages:
        assert s.tool_id in content
