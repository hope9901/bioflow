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

GENOMES = REPO / "data" / "test" / "genomes_small"
G1 = GENOMES / "genome1.fna"
G2 = GENOMES / "genome2.fna"

GWAS = REPO / "data" / "test" / "gwas_small"
GWAS_GPA = GWAS / "gene_presence_absence.csv"
GWAS_TRAITS = GWAS / "traits.csv"


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


@pytest.mark.skipif(not G1.exists(), reason="genomes_small fixture missing")
def test_amr_vf_catalogue_full_chain(_runtime):
    """ABRicate fan-out (2 genomes × 2 DBs) end-to-end.

    abricate bundles its own databases, so this needs no external DB.
    phiX carries no AMR / plasmid genes, so the TSVs contain only the
    header — which is exactly what proves abricate ran and wrote output
    for every (genome, db) pair.
    """
    from bioflow.recipes import get

    ws = _runtime
    results = get("amr_vf_catalogue")(
        out_dir=ws / "out",
        genome_paths=[G1, G2],
        dbs=("vfdb", "plasmidfinder"),
    )

    # Fan-out returns one StageResult per (genome, db) pair.
    assert isinstance(results, list)
    assert len(results) == 4, f"expected 4 abricate runs, got {len(results)}"
    assert all(r.ok for r in results), "an abricate run failed"

    # Every pair produced its TSV with the canonical ABRicate header.
    tsvs = list(ws.rglob("*.tsv"))
    abr = [t for t in tsvs if t.read_text(errors="replace").startswith("#FILE")]
    assert len(abr) >= 4, f"expected ≥4 ABRicate TSVs, found {len(abr)}"
    for t in abr:
        assert "DATABASE" in t.read_text(errors="replace").splitlines()[0]


@pytest.mark.skipif(not G1.exists(), reason="genomes_small fixture missing")
def test_ani_matrix_full_chain(_runtime):
    """All-vs-all FastANI end-to-end on two external genomes.

    Regression guard for the list-file path bug: FastANI reads genome
    paths from a list file (not the command), so the recipe must stage
    the genomes into the workspace and write *container* paths — external
    genomes used to fail with 'Could not open <host path>'.
    """
    from bioflow.recipes import get

    ws = _runtime
    result = get("ani_matrix")(out_dir=ws / "out", genome_paths=[G1, G2])
    assert result.ok, f"ani_matrix failed: {(result.stderr or '')[:500]}"

    mat = _find_one(ws, "ani_matrix.tsv")
    assert mat is not None, "no ani_matrix.tsv produced"
    rows = [r for r in mat.read_text().splitlines() if r.strip()]
    # 2 genomes all-vs-all → up to 4 rows; the cross pair must be present
    # with a high ANI (the two genomes differ by only 25 SNPs).
    assert rows, "ANI matrix is empty"
    cross = [r for r in rows if r.split("\t")[0] != r.split("\t")[1]]
    assert cross, "no cross-genome ANI row"
    ani = float(cross[0].split("\t")[2])
    assert ani > 95.0, f"expected high ANI for near-identical genomes, got {ani}"


@pytest.mark.skipif(not G1.exists(), reason="genomes_small fixture missing")
def test_pangenome_full_chain(_runtime):
    """Prokka × N (fan-out) → Roary end-to-end on two external genomes."""
    from bioflow.recipes import get

    ws = _runtime
    # _genome_paths is the recipe's test hatch that skips the NCBI fetch.
    result = get("pangenome")(
        taxon="test", out_dir=ws / "out", _genome_paths=[G1, G2],
    )
    assert result.ok, f"pangenome failed: {(result.stderr or '')[:500]}"

    # Roary's core artifact.
    gpa = _find_one(ws, "gene_presence_absence.csv")
    assert gpa is not None, "no Roary gene_presence_absence.csv"

    summary = _find_one(ws, "summary_statistics.txt")
    assert summary is not None, "no Roary summary_statistics.txt"
    # The two near-identical genomes share their genes as core.
    body = summary.read_text()
    assert "Core genes" in body
    assert "Total genes" in body


@pytest.mark.skipif(not GWAS_GPA.exists(), reason="gwas_small fixture missing")
def test_gwas_full_chain(_runtime):
    """Scoary GWAS end-to-end on a synthetic Roary GPA + phenotype."""
    from bioflow.recipes import get

    ws = _runtime
    result = get("gwas")(
        traits_csv=GWAS_TRAITS, gpa_csv=GWAS_GPA, out_dir=ws / "out",
    )
    assert result.ok, f"gwas failed: {(result.stderr or '')[:500]}"

    # Scoary writes <Trait>.results.csv (one per phenotype column).
    res = _find_one(ws, "Resistant.results.csv")
    assert res is not None, "no Scoary results CSV"
    text = res.read_text(errors="replace")
    assert "Benjamini_H_p" in text.splitlines()[0], "missing Scoary stat columns"
    # The perfectly-associated gene must surface as a hit.
    assert "gene_0005" in text, "Scoary missed the planted association"
