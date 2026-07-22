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
from bioflow.recipes import register, choice


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
    """Comet: database search, mzML + FASTA → Percolator input (``.pin``).

    Percolator's input is the tab-delimited ``.pin``, **not** pepXML (feeding it
    ``.pep.xml`` fails with "not tab delimited"), so the params are forced to
    ``output_percolatorfile=1``.  ``decoy_search=1`` lets Comet build its own
    decoys, so ``fasta_db`` is a plain target-only FASTA (shared with the MS-GF+
    branch).  ``-P``/``-D`` must be joined to their flags (no space).
    """
    params = f"{out_dir}/comet.params"
    return (
        f"bash -c '"
        f"cp {comet_params} {params} && "
        f"sed -i \"s/^decoy_search.*/decoy_search = 1/; "
        f"s/^output_percolatorfile.*/output_percolatorfile = 1/\" {params} && "
        f"for f in {mzml.out_dir}/*.mzML; do "
        f"  comet -P{params} -D{fasta_db} \"$f\"; "
        f"done && "
        f"mv {mzml.out_dir}/*.pin {out_dir}/ 2>/dev/null || true'"
    )


@stage(image="quay.io/biocontainers/percolator:3.9--h0f90025_0",
       cpu=4, ram_gb=16, depends_on=comet_search)
def percolator_fdr(search, *, out_dir, fdr_threshold: float = 0.01):
    """Percolator: machine-learned FDR control on Comet's ``.pin`` output.

    Outputs a per-PSM table with q-values plus a ``passing_psms.tsv`` filtered
    at ``fdr_threshold`` (default 1% FDR, the q-value in column 3).
    """
    return (
        f"bash -c '"
        f"for f in {search.out_dir}/*.pin; do "
        f"  base=$(basename \"$f\" .pin); "
        f"  percolator --results-psms {out_dir}/$base.psms.tsv \"$f\"; "
        f"done && "
        # 1% FDR cut for downstream.  -F must reach awk as the two chars
        # \\t (which awk reads as a tab); a bare -F\\t would have its
        # backslash stripped by bash, leaving the field separator the
        # literal letter 't'.  Double-quoting keeps the backslash.
        f"awk -F\"\\t\" -v q={fdr_threshold} "
        f"      \"NR==1 || \\$3 < q\" "
        f"      {out_dir}/*.psms.tsv > {out_dir}/passing_psms.tsv'"
    )


@stage(image="quay.io/biocontainers/msgf_plus:2024.03.26--hdfd78af_0",
       cpu=8, ram_gb=16, depends_on=msconvert,
       retry=2, retry_with={"ram_gb": "2x"})
def msgf_search(mzml, fasta_db: Path, *, out_dir, instrument: int = 0):
    """MS-GF+ database search (``--set search=msgf``) → mzIdentML.

    A drop-in-input alternative to Comet: same mzML + target FASTA.  ``-tda 1``
    runs a concatenated target-decoy search so MS-GF+'s own QValue is available
    (msgf2pin, the Percolator bridge, isn't packaged in any BioContainer, so the
    MS-GF+ branch uses MS-GF+'s built-in FDR instead of Percolator).
    ``-inst`` is the analyzer (0 = low-res, 1 = Orbitrap/FT, 3 = Q-Exactive).
    """
    return (
        f"bash -c '"
        f"for f in {mzml.out_dir}/*.mzML; do "
        f"  base=$(basename \"$f\" .mzML); "
        f"  msgf_plus -s \"$f\" -d {fasta_db} -tda 1 -inst {instrument} "
        f"    -t 20ppm -m 0 -o {out_dir}/$base.mzid; "
        f"done'"
    )


@stage(image="quay.io/biocontainers/msgf_plus:2024.03.26--hdfd78af_0",
       cpu=4, ram_gb=16, depends_on=msgf_search)
def msgf_fdr(search, *, out_dir, fdr_threshold: float = 0.01):
    """MS-GF+ FDR: mzIdentML → TSV → ``passing_psms.tsv`` at ``fdr_threshold``.

    ``MzIDToTsv`` flattens each mzid; then the QValue column (found by name, its
    position varies) is thresholded — the same ``passing_psms.tsv`` the
    Percolator branch writes, so anything downstream is caller-agnostic.
    """
    return (
        f"bash -c '"
        f"for f in {search.out_dir}/*.mzid; do "
        f"  base=$(basename \"$f\" .mzid); "
        f"  msgf_plus edu.ucsd.msjava.ui.MzIDToTsv -i \"$f\" "
        f"    -o {out_dir}/$base.tsv; "
        f"done && "
        f"awk -F\"\\t\" -v q={fdr_threshold} "
        f"    \"NR==1{{for(i=1;i<=NF;i++) if(\\$i==\\\"QValue\\\") c=i; print; next}} "
        f"     c && \\$c < q\" "
        f"    {out_dir}/*.tsv > {out_dir}/passing_psms.tsv'"
    )


# ── Pipeline ────────────────────────────────────────────────────────────────

@pipeline(
    stages=[msconvert, comet_search, percolator_fdr, msgf_search, msgf_fdr],
    description="LC-MS/MS DDA proteomics: msconvert → Comet/MS-GF+ → FDR",
)
def proteomics_dda(
    raw_dir: Path,
    fasta_db: Path,
    *,
    out_dir: Path,
    search: str = "comet",
    comet_params: Path | None = None,
    fdr_threshold: float = 0.01,
):
    """End-to-end DDA proteomics, fully open-source stack.

    ``search`` selects the engine **and** its FDR: ``"comet"`` (default; Comet →
    Percolator) or ``"msgf"`` (``--set search=msgf``; MS-GF+ → its built-in
    target-decoy FDR).  GATK-style, the two can't share one FDR step — Percolator
    needs a ``.pin`` and the msgf2pin bridge isn't packaged anywhere — so the
    MS-GF+ branch swaps the whole search + FDR pair.  Both write the same
    ``passing_psms.tsv``.  ``fasta_db`` is target-only; each engine makes its own
    decoys.
    """
    search = choice("search", search, "comet", "msgf")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mz = msconvert(Path(raw_dir))
    if search == "msgf":
        hits = msgf_search(mz, Path(fasta_db))
        return msgf_fdr(hits, fdr_threshold=fdr_threshold)

    if comet_params is None:
        raise ValueError("search='comet' needs --comet-params")
    hits = comet_search(mz, Path(comet_params), Path(fasta_db))
    return percolator_fdr(hits, fdr_threshold=fdr_threshold)


register("proteomics_dda", proteomics_dda)
