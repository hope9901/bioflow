"""LC-MS/MS DDA proteomics recipe — open-source stack.

End-to-end workflow:
    msconvert (vendor → mzML)
        → Comet (database search, mzML + FASTA → pep.xml)
        → Percolator (FDR control on pep.xml)

The previous version of this recipe used FragPipe/MSFragger, but those
projects do not publish a public Docker image (`fcyu/fragpipe:22.0`
and `fcyu/msfragger:4.1` are not on Docker Hub and the licenses
prohibit BioContainers redistribution).  The current stack uses
fully open-source, publicly-pullable BioContainers:

  * msconvert: ProteoWizard's vendor → mzML converter
  * Comet:     well-established C++ search engine
  * Percolator: machine-learned FDR rescoring

Inputs
------
* ``raw_dir``       directory containing vendor-format spectra
                    (.raw / .d / .wiff) — these are converted to mzML
* ``fasta_db``      protein FASTA database (target + decoys for FDR)
* ``comet_params``  Comet's ``comet.params`` config file

Researcher (Tier B) usage::

    bioflow recipe run proteomics_dda \\
        --raw-dir /data/raw \\
        --fasta-db /refs/human_uniprot_decoy.fa \\
        --comet-params /refs/comet.params \\
        --out ./out

If you have access to FragPipe / MSFragger locally and want to use
them instead, see ``docs/maintainer/proteomics_msfragger.md`` for the
build-your-own-image recipe.
"""
from __future__ import annotations

from pathlib import Path

from bioflow import stage, pipeline
from bioflow.recipes import register


# ── Stages ───────────────────────────────────────────────────────────────────

@stage(image="chambm/pwiz-skyline-i-agree-to-the-vendor-licenses:latest",
       cpu=4, ram_gb=8)
def msconvert(raw_dir: Path, *, out_dir):
    """msconvert: vendor (.raw / .d / .wiff) → mzML with vendor peak-picking.

    The ProteoWizard image ships ``msconvert`` only as a Windows
    ``msconvert.exe`` under ``/wineprefix64`` — there is no ``msconvert``
    on ``PATH``, so it must be launched through ``wine`` (the image's
    documented invocation).  Calling ``msconvert`` directly would fail
    with ``command not found``.
    """
    return (
        f"sh -c 'for f in {raw_dir}/*.raw {raw_dir}/*.d {raw_dir}/*.wiff; "
        f"do [ -e \\\"$f\\\" ] && wine msconvert \\\"$f\\\" --mzML "
        f"--filter \\\"peakPicking vendor msLevel=1-\\\" "
        f"--outdir {out_dir}; done'"
    )


@stage(image="quay.io/biocontainers/comet-ms:2026011--h9ee0642_0",
       cpu=8, ram_gb=16, depends_on=msconvert,
       retry=2, retry_with={"ram_gb": "2x"})
def comet_search(mzml, comet_params: Path, fasta_db: Path, *, out_dir):
    """Comet: database search, mzML + FASTA → pep.xml.

    The Comet binary needs ``-P<params>`` and ``-D<fasta>`` joined to
    their flags (no space).  We loop over every mzML produced by the
    previous stage.
    """
    return (
        f"bash -c '"
        f"cd {out_dir} && "
        f"for f in {mzml.out_dir}/*.mzML; do "
        f"  comet -P{comet_params} -D{fasta_db} \"$f\"; "
        f"done && "
        f"mv {mzml.out_dir}/*.pep.xml {out_dir}/ 2>/dev/null || true'"
    )


@stage(image="quay.io/biocontainers/percolator:3.7.1--h3b5f4bd_2",
       cpu=4, ram_gb=16, depends_on=comet_search)
def percolator_fdr(search, *, out_dir, fdr_threshold: float = 0.01):
    """Percolator: machine-learned FDR control on Comet pep.xml outputs.

    Outputs a per-PSM table with q-values plus a target-PSM TSV
    filtered at ``fdr_threshold`` (default 1% FDR).
    """
    return (
        f"bash -c '"
        f"for f in {search.out_dir}/*.pep.xml; do "
        f"  base=$(basename \"$f\" .pep.xml); "
        f"  percolator --xmloutput {out_dir}/$base.pout.xml "
        f"             --results-psms {out_dir}/$base.psms.tsv "
        f"             \"$f\"; "
        f"done && "
        # 1% FDR cut for downstream.  -F must reach awk as the two chars
        # \\t (which awk reads as a tab); a bare -F\\t would have its
        # backslash stripped by bash, leaving the field separator the
        # literal letter 't'.  Double-quoting keeps the backslash.
        f"awk -F\"\\t\" -v q={fdr_threshold} "
        f"      \"NR==1 || \\$3 < q\" "
        f"      {out_dir}/*.psms.tsv > {out_dir}/passing_psms.tsv'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[msconvert, comet_search, percolator_fdr],
    description="LC-MS/MS DDA proteomics: msconvert → Comet → Percolator",
)
def proteomics_dda(
    raw_dir: Path,
    fasta_db: Path,
    comet_params: Path,
    *,
    out_dir: Path,
    fdr_threshold: float = 0.01,
):
    """End-to-end DDA proteomics, fully open-source stack."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mz = msconvert(Path(raw_dir))
    search = comet_search(mz, Path(comet_params), Path(fasta_db))
    return percolator_fdr(search, fdr_threshold=fdr_threshold)


register("proteomics_dda", proteomics_dda)
