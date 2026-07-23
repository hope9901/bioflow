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
