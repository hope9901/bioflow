"""Regression guards for the two recipes whose fixtures had no test.

``scrna_small`` and ``proteomics_small`` were built to verify the kb-python and
MS-GF+ swaps, then committed without anything exercising them — so the work they
proved could regress silently. That matters most for proteomics: Percolator
cannot read Comet's ``.pep.xml`` ("not tab delimited"), and the fix (Comet emits
a ``.pin``) had no test protecting it.

Both recipes run stages whose *tails* need more data than a tiny fixture can
give (Scanpy's PCA/clustering needs far more than 3 genes; Percolator's
semi-supervised FDR needs far more than 3 PSMs), so these assert the part the
fixture can prove: each stage produces the artifact the next one consumes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bioflow import set_backend, set_workspace
from bioflow.core.runner import DockerBackend

try:
    _docker_unavailable = None
    DockerBackend()
except Exception as exc:  # pragma: no cover - depends on host
    _docker_unavailable = str(exc)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.slow,
    pytest.mark.skipif(
        _docker_unavailable is not None,
        reason=f"Docker not reachable: {_docker_unavailable}",
    ),
]

REPO = Path(__file__).resolve().parents[2]
SCRNA = REPO / "data" / "test" / "scrna_small"
PROT = REPO / "data" / "test" / "proteomics_small"
META = REPO / "data" / "test" / "metagenome_small"
COHORT = REPO / "data" / "test" / "cohort_small"
PHIX = REPO / "data" / "test" / "phix_small"


def _build_bowtie2_index(ws: Path) -> Path:
    """Build a Bowtie2 index from the phiX reference inside the workspace.

    ATAC/ChIP take a *prebuilt* index (real ones are large and belong to the
    user), so the test builds a tiny one rather than committing index files.
    Uses the same Bowtie2 image the recipe does, via bioflow's backend so the
    mount works on every OS.  Returns the index prefix.
    """
    import shutil

    from bioflow.core.runner import make_backend

    idx = ws / "bt2idx"
    idx.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PHIX / "reference.fa", idx / "phix.fa")
    res = make_backend().run(
        image="staphb/bowtie2:2.5.1",
        command="bowtie2-build /idx/phix.fa /idx/phix",
        mounts={str(idx): "/idx"},
        cpu=1, ram_gb=2, workdir="/idx",
    )
    assert res.exit_code == 0, f"bowtie2-build failed: {res.stderr or res.stdout}"
    return idx / "phix"


@pytest.fixture
def workspace(tmp_path):
    set_workspace(tmp_path / "ws")
    set_backend(DockerBackend())
    yield tmp_path / "ws"
    set_backend(None)


# ── scrna_seq: --set counter=kb ──────────────────────────────────────────────

@pytest.mark.skipif(not SCRNA.exists(), reason="scrna_small fixture missing")
def test_kb_counter_produces_a_scanpy_readable_matrix(workspace):
    """kb ref → kb count must emit the cells×genes matrix Scanpy's reader takes."""
    from bioflow.recipes.single_cell.scrna_seq import kb_count, kb_ref

    ref = kb_ref(SCRNA / "genome.fa", SCRNA / "genes.gtf")
    assert ref.ok, (ref.stderr or ref.stdout)[-400:]
    assert (Path(ref.out_dir) / "t2g.txt").exists(), "kb ref wrote no t2g"

    counts = kb_count(SCRNA / "reads_R1.fastq.gz", SCRNA / "reads_R2.fastq.gz",
                      ref, SCRNA / "whitelist.txt")
    assert counts.ok, (counts.stderr or counts.stdout)[-400:]

    mtx = Path(counts.out_dir) / "counts_unfiltered" / "cells_x_genes.mtx"
    assert mtx.exists(), "kb count wrote no cells_x_genes.mtx"
    # MatrixMarket dimension line: <cells> <genes> <nonzero>
    dims = mtx.read_text(encoding="utf-8").splitlines()[2].split()
    cells, genes, nonzero = (int(x) for x in dims)
    assert (cells, genes) == (6, 3), f"expected the 6-cell × 3-gene fixture, got {dims}"
    assert nonzero == 12, "each cell should express 2 of the 3 genes"

    # The sidecar files Scanpy's reader needs alongside the matrix.
    for sidecar in ("cells_x_genes.barcodes.txt", "cells_x_genes.genes.txt"):
        assert (mtx.parent / sidecar).exists(), f"missing {sidecar}"


# ── proteomics_dda: the Percolator input format ──────────────────────────────

@pytest.mark.skipif(not PROT.exists(), reason="proteomics_small fixture missing")
def test_comet_emits_a_percolator_pin_not_pepxml(workspace):
    """The regression guard: Percolator's input is a tab-delimited ``.pin``.

    The recipe used to hand it Comet's ``.pep.xml``, which Percolator rejects
    outright, so the default path could not have worked on real data.
    """
    import shutil

    from bioflow.recipes.proteomics.proteomics_dda import comet_search

    # Stand in for the msconvert stage: its output lives *inside* the workspace,
    # which is what gets mounted into the container. (Pointing straight at the
    # repo fixture would leave the glob looking at an unmounted host path.)
    spectra_dir = workspace / "spectra"
    spectra_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROT / "spectra.mgf", spectra_dir / "spectra.mgf")

    class _Spectra:
        out_dir = spectra_dir   # comet_search globs <mzml.out_dir>/*.{mzML,mgf,…}

    search = comet_search(_Spectra(), PROT / "comet.params", PROT / "target.fasta")
    assert search.ok, (search.stderr or search.stdout)[-500:]

    pins = list(Path(search.out_dir).glob("*.pin"))
    assert pins, (
        "Comet produced no .pin — the recipe must force "
        "output_percolatorfile=1, or Percolator cannot read its input"
    )
    header = pins[0].read_text(encoding="utf-8").splitlines()[0]
    assert "\t" in header, ".pin must be tab-delimited for Percolator"
    for column in ("SpecId", "Label", "Peptide"):
        assert column in header, f".pin header missing {column}"


# ── metagenome_assembly: assemble → coverage → binning ───────────────────────

@pytest.mark.skipif(not META.exists(), reason="metagenome_small fixture missing")
def test_metagenome_assembly_binning_consumes_the_assembly(workspace):
    """fastp → MEGAHIT must produce contigs that the binner then consumes.

    This recipe had no automated coverage at all, and the maxbin2 swap it gained
    was never guarded. A tiny synthetic metagenome can't yield real bins (the
    binners need marker genes / many contigs the fixture doesn't have), so this
    stops at the hand-off: MEGAHIT assembles, MetaBAT2 reads the contigs, and the
    ``bins/`` layout CheckM2 expects exists.
    """
    from bioflow.recipes.metagenomics.metagenome_assembly import (
        assemble, bin_genomes, map_back, qc_trim,
    )

    clean = qc_trim(META / "reads_R1.fastq.gz", META / "reads_R2.fastq.gz")
    assert clean.ok, (clean.stderr or clean.stdout)[-400:]

    asm = assemble(clean)
    assert asm.ok, (asm.stderr or asm.stdout)[-400:]
    contigs = Path(asm.out_dir) / "megahit" / "final.contigs.fa"
    assert contigs.exists(), "MEGAHIT wrote no final.contigs.fa"
    n_contigs = contigs.read_text(encoding="utf-8").count(">")
    assert n_contigs >= 2, f"expected the 2-organism assembly, got {n_contigs} contigs"

    mapped = map_back(asm, clean)
    assert mapped.ok, (mapped.stderr or mapped.stdout)[-400:]
    assert (Path(mapped.out_dir) / "mapped.bam").exists(), "no coverage BAM"

    binned = bin_genomes(mapped, asm)
    assert binned.ok, (binned.stderr or binned.stdout)[-400:]
    # MetaBAT2 computes a real depth table over both contigs and writes bins/.
    depth = Path(binned.out_dir) / "depth.txt"
    assert depth.exists() and depth.read_text().count("\n") >= 3, \
        "MetaBAT2 wrote no per-contig depth table"
    assert (Path(binned.out_dir) / "bins").is_dir(), \
        "no bins/ directory for CheckM2 to consume"


# ── joint_genotyping: cohort gVCF → combine → genotype ───────────────────────

@pytest.mark.skipif(not (COHORT.exists() and PHIX.exists()),
                    reason="cohort_small / phix_small fixture missing")
def test_joint_genotyping_produces_a_multisample_cohort_vcf(workspace):
    """The GATK cohort path must merge per-sample gVCFs into one multi-sample VCF.

    This recipe had no automated coverage, so its fan-out + converge — the shape
    the GLnexus swap plugs into — went unchecked. Two samples (the same phiX
    reads) are called against a reference with 5 planted SNPs; the cohort must
    carry both samples and all five variants. The final SnpEff stage is left out
    on purpose: it downloads its DB from S3 at run time, which would make CI
    network-dependent.
    """
    from bioflow.recipes.variant_calling.joint_genotyping import (
        align_one, call_gvcf, combine_gvcfs, genotype_cohort, prepare_reference,
        qc_one,
    )

    ref = COHORT / "reference.fa"
    r1, r2 = PHIX / "sim_R1.fastq.gz", PHIX / "sim_R2.fastq.gz"

    prepare_reference(ref)          # BWA index + .fai + .dict, once
    gvcfs = []
    for sid in ("sampleA", "sampleB"):
        clean = qc_one(sid, r1, r2)
        assert clean.ok, (clean.stderr or clean.stdout)[-300:]
        aln = align_one(sid, clean, ref)
        assert aln.ok, (aln.stderr or aln.stdout)[-300:]
        gvcf = call_gvcf(sid, aln, ref)
        assert gvcf.ok, (gvcf.stderr or gvcf.stdout)[-300:]
        gvcfs.append(gvcf)

    combined = combine_gvcfs(gvcfs, ref)
    assert combined.ok, (combined.stderr or combined.stdout)[-300:]

    cohort = genotype_cohort(combined, ref)
    assert cohort.ok, (cohort.stderr or cohort.stdout)[-300:]
    vcf = Path(cohort.out_dir) / "cohort.vcf.gz"
    assert vcf.exists(), "GenotypeGVCFs wrote no cohort.vcf.gz"

    # bgzipped VCF — read it straight, no second container or path juggling.
    import gzip

    samples: list[str] = []
    n_records = 0
    with gzip.open(vcf, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#CHROM"):
                samples = line.rstrip("\n").split("\t")[9:]
            elif not line.startswith("#"):
                n_records += 1
    assert {"sampleA", "sampleB"} <= set(samples), \
        f"cohort VCF is not multi-sample: {samples}"
    assert n_records >= 5, (
        f"expected the 5 planted SNPs in the cohort, got {n_records}"
    )


# ── atac_seq: trim → align → dedup → peaks ───────────────────────────────────

@pytest.mark.skipif(not PHIX.exists(), reason="phix_small fixture missing")
def test_atac_seq_align_dedup_peaks(workspace):
    """trim → Bowtie2 align → Picard dedup → MACS3 peaks on phiX.

    This recipe had no automated coverage, and the gap hid a real defect: the
    Bowtie2 image it pinned shipped a samtools that couldn't load
    (``libdeflate.so.0``), so ``bowtie2 | samtools sort`` — the default align
    path of *both* atac_seq and chip_seq — failed on real data. The guard runs
    that chain end to end so it can't regress.

    TOBIAS footprinting (the last stage) needs a motif/genome scale a phiX toy
    can't provide, so the guard stops at peak calling.
    """
    from bioflow.recipes.epigenomics.atac_seq import (
        align, call_peaks, dedup, trim,
    )

    idx = _build_bowtie2_index(workspace)
    clean = trim(PHIX / "sim_R1.fastq.gz", PHIX / "sim_R2.fastq.gz")
    assert clean.ok, (clean.stderr or clean.stdout)[-300:]

    aln = align(clean, idx, "s1")
    assert aln.ok, (
        "Bowtie2 align failed — the pinned image's samtools must load "
        f"(the libdeflate regression): {(aln.stderr or aln.stdout)[-300:]}"
    )
    assert (Path(aln.out_dir) / "s1.bam").exists(), "no sorted BAM"

    dd = dedup(aln, "s1")
    assert dd.ok, (dd.stderr or dd.stdout)[-300:]

    peaks = call_peaks(dd, "s1", "1e7")
    assert peaks.ok, (peaks.stderr or peaks.stdout)[-300:]
    narrow = list(Path(peaks.out_dir).rglob("*.narrowPeak"))
    assert narrow, "MACS3 wrote no narrowPeak file"
