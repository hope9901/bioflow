"""Full-pipeline end-to-end test — the whole recipe, not just stage 1.

The smoke matrix (test_recipe_smoke_matrix.py) validates each recipe's
*first* stage against a real container.  This goes the full distance:
``prokaryote_assembly`` from raw reads all the way through
``fastp → SPAdes → QUAST → Prokka`` on the phiX174 fixture, asserting
that data actually flows between stages and every container produces its
expected output.

phiX174 at ~56× assembles into a single ~5.4 kb contig in well under a
minute; the whole chain (incl. the ~2 GB Prokka image) runs in a few
minutes.  Marked ``@pytest.mark.docker`` + ``@pytest.mark.slow`` and
auto-skipped without a daemon.

Run::

    pytest tests/integration/test_full_pipeline_e2e.py -v -m docker
"""
from __future__ import annotations

from pathlib import Path

import pytest

_docker_unavailable: str | None = None
try:
    import docker as _docker_mod  # type: ignore[import-not-found]

    _docker_mod.from_env().ping()
except Exception as exc:
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
FIX = REPO / "data" / "test" / "phix_small"
R1 = FIX / "sim_R1.fastq.gz"
R2 = FIX / "sim_R2.fastq.gz"


@pytest.fixture
def _runtime(tmp_path):
    from bioflow import DockerBackend, set_backend, set_workspace

    set_workspace(tmp_path / "ws")
    set_backend(DockerBackend())
    yield tmp_path


def _find_one(root: Path, *names: str) -> Path | None:
    for name in names:
        for p in root.rglob(name):
            if p.is_file() and p.stat().st_size > 0:
                return p
    return None


@pytest.mark.skipif(not R1.exists(), reason="phiX fixture missing")
def test_prokaryote_assembly_full_chain(_runtime):
    """fastp → SPAdes → QUAST → Prokka end-to-end on phiX174."""
    from bioflow.recipes import get

    ws = _runtime
    result = get("prokaryote_assembly")(
        r1=R1, r2=R2, out_dir=ws / "out", sample_id="phix",
    )

    # 1. The whole pipeline completed (final stage = Prokka annotation).
    assert result.ok, f"pipeline failed: {(result.stderr or '')[:500]}"

    # 2. SPAdes assembled phiX into a contig of plausible length.
    asm = _find_one(ws, "scaffolds.fasta", "contigs.fasta")
    assert asm is not None, "no assembly FASTA produced"
    seq = "".join(
        line.strip() for line in asm.read_text().splitlines()
        if not line.startswith(">")
    )
    # phiX is 5386 bp; allow generous slack for assembly trimming.
    assert 4500 <= len(seq) <= 6000, f"unexpected assembly length {len(seq)}"

    # 3. QUAST emitted its machine-readable report.
    quast = _find_one(ws, "report.tsv")
    assert quast is not None, "no QUAST report.tsv"
    assert "contigs" in quast.read_text().lower()

    # 4. Prokka annotated the assembly with at least one CDS.
    prokka_txt = _find_one(ws, "phix.txt")
    assert prokka_txt is not None, "no Prokka summary (.txt)"
    body = prokka_txt.read_text()
    assert "CDS:" in body, f"Prokka produced no CDS line:\n{body[:300]}"
