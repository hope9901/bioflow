"""End-to-end execution smoke tests for the 8 per-pipeline recipes.

These tests run each recipe through MockBackend with dummy inputs.
Unlike the registration tests in ``test_recipes_per_pipeline.py``
(which only inspect the DAG via ``dry_run()``), these exercise:

* argument unpacking (``.map`` vs ``.starmap``)
* external Path mounting via ``_collect_external_mounts``
* inter-stage data flow

If a recipe's stages cannot be threaded together — e.g. a multi-arg
stage called via ``.map`` instead of ``.starmap`` — these tests fail.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bioflow import MockBackend, set_backend, set_workspace
from bioflow.recipes import get


@pytest.fixture(autouse=True)
def _runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    set_backend(MockBackend())
    yield


def _make_fastq_pair(d: Path, prefix: str = "reads"):
    r1 = d / f"{prefix}_R1.fq.gz"
    r2 = d / f"{prefix}_R2.fq.gz"
    r1.write_text("@r1\n", encoding="utf-8")
    r2.write_text("@r2\n", encoding="utf-8")
    return r1, r2


class TestExecution:

    def test_prokaryote_assembly_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        result = get("prokaryote_assembly")(
            r1=r1, r2=r2, out_dir=tmp_path / "out", sample_id="demo",
        )
        assert result.ok

    def test_eukaryote_assembly_runs(self, tmp_path):
        lr = tmp_path / "ont.fq.gz"
        lr.write_text("@r\nACGT\n+\nIIII\n", encoding="utf-8")
        result = get("eukaryote_assembly")(
            long_reads=lr, out_dir=tmp_path / "out",
        )
        assert result.ok

    def test_metagenome_assembly_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        result = get("metagenome_assembly")(
            r1=r1, r2=r2, out_dir=tmp_path / "out", sample_id="env",
        )
        assert result.ok

    def test_germline_variants_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        ref = tmp_path / "ref.fa"
        ref.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
        result = get("germline_variants")(
            r1=r1, r2=r2, reference=ref, snpeff_db="test_db",
            out_dir=tmp_path / "out", sample_id="s",
        )
        assert result.ok

    def test_joint_genotyping_runs(self, tmp_path):
        """Cohort joint genotyping: fan-out per sample → converge."""
        d = tmp_path / "reads"; d.mkdir()
        rows = ["sample_id,fastq_r1,fastq_r2"]
        for s in ("s1", "s2", "s3"):
            r1 = d / f"{s}_R1.fq.gz"; r1.write_text("@x", encoding="utf-8")
            r2 = d / f"{s}_R2.fq.gz"; r2.write_text("@x", encoding="utf-8")
            rows.append(f"{s},{r1},{r2}")
        sheet = tmp_path / "cohort.csv"
        sheet.write_text("\n".join(rows) + "\n", encoding="utf-8")
        ref = tmp_path / "ref.fa"
        ref.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")

        result = get("joint_genotyping")(
            sample_sheet=sheet, reference=ref, snpeff_db="test_db",
            out_dir=tmp_path / "out",
        )
        assert result.ok

    def test_rnaseq_deg_runs(self, tmp_path):
        d = tmp_path / "reads"
        d.mkdir()
        for s in ("s1", "s2", "s3", "s4"):
            (d / f"{s}_R1.fq.gz").write_text("@x", encoding="utf-8")
            (d / f"{s}_R2.fq.gz").write_text("@x", encoding="utf-8")
        sheet = tmp_path / "samples.csv"
        sheet.write_text(
            "sample_id,fastq_r1,fastq_r2,condition\n"
            f"s1,{d / 's1_R1.fq.gz'},{d / 's1_R2.fq.gz'},treated\n"
            f"s2,{d / 's2_R1.fq.gz'},{d / 's2_R2.fq.gz'},treated\n"
            f"s3,{d / 's3_R1.fq.gz'},{d / 's3_R2.fq.gz'},control\n"
            f"s4,{d / 's4_R1.fq.gz'},{d / 's4_R2.fq.gz'},control\n",
            encoding="utf-8",
        )
        ref = tmp_path / "ref.fa"
        ref.write_text(">x\nACGT\n", encoding="utf-8")

        result = get("rnaseq_deg")(
            sample_sheet=sheet, transcriptome=ref,
            out_dir=tmp_path / "out",
        )
        assert result.ok

    def test_metagenomics_profile_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        db = tmp_path / "k2db"
        db.mkdir()
        result = get("metagenomics_profile")(
            r1=r1, r2=r2, kraken2_db=db,
            out_dir=tmp_path / "out", sample_id="s",
        )
        assert result.ok

    def test_scrna_seq_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        idx = tmp_path / "star"
        idx.mkdir()
        wl = tmp_path / "wl.txt"
        wl.write_text("AAAAAAAAAAAAAAAA\n", encoding="utf-8")
        result = get("scrna_seq")(
            r1=r1, r2=r2, star_index=idx, whitelist=wl,
            out_dir=tmp_path / "out",
        )
        assert result.ok

    def test_chip_seq_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        b2 = tmp_path / "bt2"
        b2.mkdir()
        (b2 / "hg.1.bt2").write_text("x", encoding="utf-8")
        ref = tmp_path / "hg.fa"
        ref.write_text(">x\nACGT\n", encoding="utf-8")
        gtf = tmp_path / "hg.gtf"
        gtf.write_text("# gtf\n", encoding="utf-8")

        result = get("chip_seq")(
            r1=r1, r2=r2, bowtie2_index=b2 / "hg",
            reference=ref, annotation=gtf,
            out_dir=tmp_path / "out", sample_id="s",
        )
        assert result.ok

    def test_atac_seq_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        b2 = tmp_path / "bt2"
        b2.mkdir()
        (b2 / "hg.1.bt2").write_text("x", encoding="utf-8")
        ref = tmp_path / "hg.fa"
        ref.write_text(">x\nACGT\n", encoding="utf-8")

        result = get("atac_seq")(
            r1=r1, r2=r2, bowtie2_index=b2 / "hg", reference=ref,
            out_dir=tmp_path / "out", sample_id="s",
        )
        assert result.ok

    def test_methylation_wgbs_runs(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        bg = tmp_path / "bisgen"
        bg.mkdir()
        result = get("methylation_wgbs")(
            r1=r1, r2=r2, bismark_genome=bg,
            out_dir=tmp_path / "out", sample_id="s",
        )
        assert result.ok

    def test_proteomics_dda_runs(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        params = tmp_path / "comet.params"
        params.write_text("# comet params\n", encoding="utf-8")
        fdb = tmp_path / "uniprot.fa"
        fdb.write_text(">x\nMKK\n", encoding="utf-8")

        result = get("proteomics_dda")(
            raw_dir=raw, comet_params=params, fasta_db=fdb,
            out_dir=tmp_path / "out",
        )
        assert result.ok


class TestExternalInputsMounted:
    """Spot-check that external file inputs are bind-mounted into the
    container's command for two recipes that take heterogeneous inputs.
    """

    def _spy(self):
        captured: list = []
        class Spy(MockBackend):
            def run(self, **kw):
                captured.append(kw)
                return super().run(**kw)
        return captured, Spy()

    def test_rnaseq_deg_sample_sheet_mounted(self, tmp_path):
        d = tmp_path / "reads"
        d.mkdir()
        for s in ("s1", "s2"):
            (d / f"{s}_R1.fq.gz").write_text("@x", encoding="utf-8")
            (d / f"{s}_R2.fq.gz").write_text("@x", encoding="utf-8")
        sheet = tmp_path / "samples.csv"
        sheet.write_text(
            "sample_id,fastq_r1,fastq_r2,condition\n"
            f"s1,{d / 's1_R1.fq.gz'},{d / 's1_R2.fq.gz'},treated\n"
            f"s2,{d / 's2_R1.fq.gz'},{d / 's2_R2.fq.gz'},control\n",
            encoding="utf-8",
        )
        ref = tmp_path / "ref.fa"
        ref.write_text(">x\nACGT\n", encoding="utf-8")

        captured, spy = self._spy()
        set_backend(spy)
        get("rnaseq_deg")(
            sample_sheet=sheet, transcriptome=ref,
            out_dir=tmp_path / "out",
        )

        # The deseq2 stage must reference /inputs/<n>/... not the host path
        deseq2_cmds = [c for c in captured if "DESeq" in c["command"]]
        assert deseq2_cmds, "deseq2 stage was not captured"
        cmd = deseq2_cmds[-1]["command"]
        assert str(sheet) not in cmd, f"raw host path leaked into command: {cmd[:200]}"
        assert "/inputs/" in cmd, f"sample_sheet not translated: {cmd[:200]}"

    def test_chip_seq_bowtie2_index_prefix_mounted(self, tmp_path):
        r1, r2 = _make_fastq_pair(tmp_path)
        b2 = tmp_path / "bt2"
        b2.mkdir()
        (b2 / "hg.1.bt2").write_text("x", encoding="utf-8")
        ref = tmp_path / "hg.fa"
        ref.write_text(">x\nACGT\n", encoding="utf-8")
        gtf = tmp_path / "hg.gtf"
        gtf.write_text("# gtf\n", encoding="utf-8")

        captured, spy = self._spy()
        set_backend(spy)
        get("chip_seq")(
            r1=r1, r2=r2, bowtie2_index=b2 / "hg",
            reference=ref, annotation=gtf,
            out_dir=tmp_path / "out", sample_id="s",
        )

        align_cmds = [c for c in captured if "bowtie2" in c["command"]]
        assert align_cmds
        cmd = align_cmds[-1]["command"]
        assert str(b2 / "hg") not in cmd
        assert "/inputs/" in cmd, f"bowtie2 index not translated: {cmd[:200]}"
