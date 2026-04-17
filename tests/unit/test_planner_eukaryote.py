"""Planner tests for eukaryote / long-read / hybrid presets (step 7)."""

from __future__ import annotations

from pathlib import Path

import yaml

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry"


def _cfg(tmp_path: Path, *, pipeline="genome_assembly", species="eukaryote",
         read_type="long_hifi", mode="de_novo", extra_inputs=None) -> Path:
    inputs = {
        "sample_id": "dmel_test",
        "busco_lineage": "insecta_odb10",
        "repeat_species": "Drosophila",
        "genome_size": "130m",
        "eggnog_db_dir": "/refs/dbs/eggnog",
        "r1_long": "/workspace/in/reads.fastq.gz",
        "r1": "/workspace/in/R1.fastq.gz",
        "r2": "/workspace/in/R2.fastq.gz",
        "reference_genome": "/refs/genomes/dm6.fa",
        "annotation_gtf": "/refs/genomes/dm6.gtf",
        "sample_sheet": "/workspace/in/samples.csv",
        "kegg_organism": "dme",
    }
    if extra_inputs:
        inputs.update(extra_inputs)
    cfg = {
        "pipeline": pipeline, "species": species,
        "read_type": read_type, "mode": mode,
        "inputs": inputs,
        "workdir": str(tmp_path / "out"),
        "registry_dir": str(REGISTRY_DIR),
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


# ── HiFi de-novo ──────────────────────────────────────────────────────────

def test_hifi_preset_six_active_stages(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset("eukaryote_denovo_hifi", _cfg(tmp_path))
    assert len(plan.stages) == 6
    assert [s.tool_id for s in plan.stages] == [
        "filtlong", "hifiasm", "busco", "earlgrey", "braker3", "eggnog_mapper"
    ]


def test_hifi_step2_gets_filtered_long_reads(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset("eukaryote_denovo_hifi", _cfg(tmp_path))
    hifiasm = next(s for s in plan.stages if s.tool_id == "hifiasm")
    expected = str(plan.workdir / "genome_assembly_step1" / "filtered.fastq.gz")
    assert hifiasm.params.get("r1_long") == expected


def test_hifi_step4_earlgrey_gets_assembly_from_step2(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset("eukaryote_denovo_hifi", _cfg(tmp_path))
    earlgrey = next(s for s in plan.stages if s.tool_id == "earlgrey")
    expected = str(plan.workdir / "genome_assembly_step2" / "asm.bp.p_ctg.fa")
    assert earlgrey.params.get("assembly_fasta") == expected


def test_hifi_step5_braker3_gets_masked_fasta(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset("eukaryote_denovo_hifi", _cfg(tmp_path))
    braker3 = next(s for s in plan.stages if s.tool_id == "braker3")
    # earlgrey → genome.masked.fasta
    expected = str(plan.workdir / "genome_assembly_step4" / "genome.masked.fasta")
    assert braker3.params.get("assembly_fasta") == expected


def test_hifi_step6_eggnog_gets_protein_faa_from_braker3(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset("eukaryote_denovo_hifi", _cfg(tmp_path))
    eggnog = next(s for s in plan.stages if s.tool_id == "eggnog_mapper")
    expected = str(plan.workdir / "genome_assembly_step5" / "braker.aa")
    assert eggnog.params.get("protein_faa") == expected


# ── Hybrid de-novo ────────────────────────────────────────────────────────

def test_hybrid_preset_six_stages(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset(
        "eukaryote_denovo_hybrid",
        _cfg(tmp_path, species="eukaryote_small", read_type="hybrid")
    )
    assert len(plan.stages) == 6
    assert plan.stages[1].tool_id == "unicycler"


def test_hybrid_step2_unicycler_gets_clean_short_reads(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset(
        "eukaryote_denovo_hybrid",
        _cfg(tmp_path, species="eukaryote_small", read_type="hybrid")
    )
    unicycler = next(s for s in plan.stages if s.tool_id == "unicycler")
    expected_r1 = str(plan.workdir / "genome_assembly_step1" / "clean_R1.fastq.gz")
    assert unicycler.params.get("r1") == expected_r1


# ── Resequencing ─────────────────────────────────────────────────────────

def test_resequencing_step2_is_bwa_mem2(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset(
        "eukaryote_resequencing",
        _cfg(tmp_path, read_type="short", mode="resequencing")
    )
    assert plan.stages[1].tool_id == "bwa_mem2"


def test_resequencing_step5_gets_consensus_fasta(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset(
        "eukaryote_resequencing",
        _cfg(tmp_path, read_type="short", mode="resequencing")
    )
    braker3 = next(s for s in plan.stages if s.tool_id == "braker3")
    # earlgrey masks the consensus → braker3 gets masked fasta
    expected = str(plan.workdir / "genome_assembly_step4" / "genome.masked.fasta")
    assert braker3.params.get("assembly_fasta") == expected


# ── Prokaryote hybrid ─────────────────────────────────────────────────────

def test_prokaryote_hybrid_skips_repeat_masking(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset(
        "prokaryote_denovo_hybrid",
        _cfg(tmp_path, species="prokaryote", read_type="hybrid", mode="de_novo")
    )
    stage_ids = [s.stage_id for s in plan.stages]
    assert "genome_assembly.step4" not in stage_ids


def test_prokaryote_hybrid_step5_bakta_gets_assembly_from_step2(tmp_path):
    from bioflow.core.planner import plan_from_preset
    plan = plan_from_preset(
        "prokaryote_denovo_hybrid",
        _cfg(tmp_path, species="prokaryote", read_type="hybrid", mode="de_novo")
    )
    bakta = next(s for s in plan.stages if s.tool_id == "bakta")
    expected = str(plan.workdir / "genome_assembly_step2" / "assembly.fasta")
    assert bakta.params.get("assembly_fasta") == expected
