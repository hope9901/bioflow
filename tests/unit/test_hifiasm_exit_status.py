"""eukaryote_assembly ``assemble_hifiasm`` must report hifiasm's own exit code.

Regression test for the 2026-11-23 nightly failure.  The stage ran
``hifiasm`` and the GFA→FASTA ``awk`` as two newline-separated commands, so
the stage's exit status was awk's.  When hifiasm died without printing
anything, the only error left was "awk: asm.bp.p_ctg.gfa: No such file or
directory", and hifiasm's real exit code was lost.  The two commands are
now chained with ``&&``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bioflow.recipes.genome_assembly.eukaryote_assembly import assemble_hifiasm

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


def _run_with_fake_hifiasm(tmp_path: Path, script: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "hifiasm"
    fake.write_text("#!/bin/sh\n" + script)
    fake.chmod(0o755)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cmd = assemble_hifiasm.func(None, Path("/reads.fastq.gz"), out_dir=out_dir)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, env=env, check=False)


def test_hifiasm_failure_exit_code_is_the_stage_exit_code(tmp_path):
    # hifiasm fails silently with a distinctive code and writes no GFA.
    proc = _run_with_fake_hifiasm(tmp_path, "exit 42\n")
    assert proc.returncode == 42
    assert "awk" not in proc.stderr, "awk ran after hifiasm failed"
    assert not (tmp_path / "out" / "assembly.fasta").exists()


def test_successful_hifiasm_still_produces_assembly_fasta(tmp_path):
    # The fake writes a one-segment GFA the way hifiasm names it (-o <prefix>).
    proc = _run_with_fake_hifiasm(
        tmp_path,
        'prefix="$2"\n'
        'printf "S\\tptg000001l\\tACGT\\n" > "${prefix}.bp.p_ctg.gfa"\n',
    )
    assert proc.returncode == 0, proc.stderr
    fasta = (tmp_path / "out" / "assembly.fasta").read_text()
    assert fasta == ">ptg000001l\nACGT\n"
