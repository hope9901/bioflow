"""End-to-end validation of a real BioContainer on real(istic) data.

Unlike test_sdk_real_docker.py (which uses alpine to prove the SDK
plumbing), this pulls an actual bioinformatics BioContainer — fastp —
and runs it on a real paired-end FASTQ fixture, asserting it produces
valid output.

This is the bridge between "MockBackend passes" and "this works on
real biology".  It is the smallest, fastest real tool we can validate
(fastp image is ~150 MB and runs in seconds on the 500-read fixture).

Marked ``@pytest.mark.docker``; auto-skipped without a daemon.
Run with::

    pytest tests/integration/test_recipe_real_data.py -m docker -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


_docker_unavailable: str | None = None
try:
    import docker as _docker_mod   # type: ignore[import-not-found]
    _docker_mod.from_env().ping()
except Exception as exc:
    _docker_unavailable = str(exc)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        _docker_unavailable is not None,
        reason=f"Docker not reachable: {_docker_unavailable}",
    ),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_R1 = REPO_ROOT / "data" / "test" / "ecoli_small" / "real_R1.fastq.gz"
FIXTURE_R2 = REPO_ROOT / "data" / "test" / "ecoli_small" / "real_R2.fastq.gz"


@pytest.fixture(autouse=True)
def _runtime(tmp_path):
    from bioflow import set_workspace, set_backend, DockerBackend
    set_workspace(tmp_path / "ws")
    set_backend(DockerBackend())
    yield


@pytest.mark.skipif(not FIXTURE_R1.exists(), reason="real FASTQ fixture missing")
def test_fastp_real_container_end_to_end(tmp_path):
    """A real fastp BioContainer trims real reads and emits valid JSON."""
    from bioflow import stage

    @stage(image="quay.io/biocontainers/fastp:0.23.4--h5f740d0_0",
           cpu=2, ram_gb=2, cache=False)
    def qc(r1, r2, *, out_dir):
        return (
            f"fastp -i {r1} -I {r2} "
            f"-o {out_dir}/clean_R1.fq.gz -O {out_dir}/clean_R2.fq.gz "
            f"--json {out_dir}/fastp.json --html {out_dir}/fastp.html --thread 2"
        )

    result = qc(FIXTURE_R1.resolve(), FIXTURE_R2.resolve())
    assert result.ok, f"fastp failed: {result.stderr[:300]}"

    out = Path(result.out_dir)
    assert (out / "clean_R1.fq.gz").exists()
    assert (out / "clean_R2.fq.gz").exists()

    report = json.loads((out / "fastp.json").read_text(encoding="utf-8"))
    # 500 pairs = 1000 reads in; high-quality fixture → most survive.
    # This is the real proof: a real BioContainer processed real reads
    # and emitted a valid, parseable JSON report.
    assert report["summary"]["before_filtering"]["total_reads"] == 1000
    assert report["summary"]["after_filtering"]["total_reads"] > 800
    # fastp records an adapter-cutting block (PE adapter detection is
    # overlap-based, so the synthetic single-end adapters may or may not
    # be trimmed — just assert the analysis ran).
    assert "adapter_cutting" in report


@pytest.mark.skipif(not FIXTURE_R1.exists(), reason="real FASTQ fixture missing")
def test_prokaryote_assembly_qc_stage_real(tmp_path):
    """The prokaryote_assembly recipe's first stage runs on real Docker.

    We invoke just the qc_trim stage (fastp) through the registered
    recipe's stage object to confirm the recipe wiring matches a real
    container, without paying for the full multi-hour SPAdes assembly.
    """
    from bioflow.recipes.genome_assembly import prokaryote_assembly as mod

    result = mod.qc_trim(FIXTURE_R1.resolve(), FIXTURE_R2.resolve())
    assert result.ok, f"qc_trim failed: {result.stderr[:300]}"
    assert (Path(result.out_dir) / "clean_R1.fastq.gz").exists()
