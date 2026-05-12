"""LC-MS/MS DDA proteomics recipe.

End-to-end workflow:
    msconvert (vendor .RAW / .d / .wiff → open mzML)
        → FragPipe (MSFragger + Percolator + Philosopher in one workflow)

FragPipe is a wrapper around MSFragger (search), Percolator (FDR),
IonQuant (label-free quant) and Philosopher (assembly + reporting).
Running it in `--headless` mode against a manifest of mzML files +
a FragPipe workflow ``.workflow`` config produces a complete proteomic
report including protein-level FDR and quant matrices.

Inputs:
    raw_dir         directory containing vendor-format spectra
                    (.raw / .d / .wiff)
    fragpipe_workflow  path to a FragPipe ``.workflow`` config file
                    (LFQ-MBR-default workflow ships with FragPipe)
    fasta_db        protein FASTA + decoys for the search

Researcher (Tier B) usage::

    bioflow recipe run proteomics_dda \\
        --raw-dir /data/raw --fragpipe-workflow LFQ-MBR.workflow \\
        --fasta-db /refs/human_uniprot_decoy.fa \\
        --out ./out
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="chambm/pwiz-skyline-i-agree-to-the-vendor-licenses:latest",
       cpu=4, ram_gb=8)
def msconvert(raw_dir: Path, *, out_dir):
    """msconvert: vendor → mzML conversion with vendor peak-picking."""
    return (
        f"sh -c 'for f in {raw_dir}/*.raw {raw_dir}/*.d {raw_dir}/*.wiff; "
        f"do [ -e \\\"$f\\\" ] && msconvert \\\"$f\\\" --mzML "
        f"--filter \\\"peakPicking vendor msLevel=1-\\\" "
        f"--outdir {out_dir}; done'"
    )


@stage(image="fcyu/fragpipe:22.0", cpu=8, ram_gb=32, depends_on=msconvert,
       retry=2, retry_with={"ram_gb": "2x"})
def fragpipe(mzml, fragpipe_workflow: Path, fasta_db: Path, *, out_dir):
    """FragPipe headless: MSFragger search + Percolator FDR + IonQuant quant.

    A minimal manifest is generated automatically from the mzML files
    produced by the previous stage (one row per mzML, default
    experiment / bioreplicate ``1``).
    """
    return (
        f"sh -c 'cd {out_dir} && "
        f"ls {mzml.out_dir}/*.mzML | "
        f"awk -F/ \\\"{{print \\$0\\\"\\t1\\t1\\tDDA\\\"}}\\\" "
        f"> manifest.tsv && "
        f"fragpipe --headless "
        f"--workflow {fragpipe_workflow} "
        f"--manifest manifest.tsv "
        f"--workdir {out_dir} "
        f"--ram 32 --threads 8'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[msconvert, fragpipe],
    description="LC-MS/MS DDA proteomics: msconvert → FragPipe",
)
def proteomics_dda(
    raw_dir: Path,
    fragpipe_workflow: Path,
    fasta_db: Path,
    *,
    out_dir: Path,
):
    """End-to-end DDA proteomics from vendor spectra to FDR-controlled hits."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mz = msconvert(Path(raw_dir))
    return fragpipe(mz, Path(fragpipe_workflow), Path(fasta_db))


register("proteomics_dda", proteomics_dda)
