"""NCBI data download — genomes and proteins.

Two data sources
----------------
Genomes (NCBI Datasets REST API v2)
    ``list_genomes()`` queries the NCBI Datasets API for assembly metadata
    filtered by taxon name or NCBI taxonomy ID.
    ``download_genomes()`` downloads a ZIP archive via the same API, extracts
    every FASTA / GFF file to *out_dir*, then removes the ZIP.

Proteins (NCBI Entrez E-utilities)
    ``list_proteins()`` uses ``esearch`` to count and preview protein records.
    ``download_proteins()`` uses ``esearch`` + ``efetch`` (batched) to stream
    a multi-FASTA suitable for use as BRAKER3 / MAKER protein-hint evidence.

Rate limits
-----------
Without an API key  →  3 requests / second.
With    an API key  → 10 requests / second.

Set the ``NCBI_API_KEY`` environment variable to use a key.
See https://www.ncbi.nlm.nih.gov/account/ to register (free).

Typical usage
-------------
    # List all complete Dickeya genomes
    bioflow ncbi search --taxon dickeya --db genome --level complete

    # Download up to 20 Dickeya genome FASTAs
    bioflow ncbi genome --taxon dickeya --out /data/genomes --level complete --max 20

    # Download RefSeq proteins from Pectobacteriaceae for BRAKER3 hints
    bioflow ncbi protein --taxon pectobacteriaceae --out /data/proteins --max 2000
"""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Sequence

if TYPE_CHECKING:
    from rich.progress import TaskID

from bioflow.core.logger import get_logger

log = get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATASETS_BASE = "https://api.ncbi.nlm.nih.gov/datasets/v2"
EUTILS_BASE   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_RATE_NO_KEY  = 0.35   # ~3 req/s
_RATE_WITH_KEY = 0.11  # ~9 req/s

# Canonical assembly level strings used in the NCBI Datasets API
_LEVEL_API: dict[str, str] = {
    "complete":   "complete_genome",
    "chromosome": "chromosome",
    "scaffold":   "scaffold",
    "contig":     "contig",
}

# Include types available for genome downloads
GENOME_INCLUDE_TYPES = (
    "GENOME_FASTA",   # genomic sequences (.fna)
    "GENOME_GFF",     # gene annotation (.gff)
    "PROT_FASTA",     # translated proteins (.faa) — annotation evidence
    "CDS_FASTA",      # coding sequences (.fna)
    "RNA_FASTA",      # transcripts (.fna)
    "GENOME_GBFF",    # GenBank flat file (.gbff)
    "SEQUENCE_REPORT",
)
# Friendly aliases — accept the natural name but translate to NCBI's API value
_INCLUDE_ALIASES = {
    "PROTEIN_FASTA": "PROT_FASTA",
    "PROTEIN":       "PROT_FASTA",
    "CDS":           "CDS_FASTA",
}

# FASTA/GFF suffixes to extract from the downloaded ZIP
_EXTRACT_SUFFIXES = (
    ".fna", ".fna.gz",
    ".faa", ".faa.gz",
    ".fa",  ".fa.gz",
    ".fasta", ".fasta.gz",
    ".gff", ".gff3", ".gff.gz",
    ".gbff", ".gbff.gz",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class NcbiError(Exception):
    """Raised when an NCBI API call fails or returns unexpected data."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AssemblyInfo:
    """Summary of a single genome assembly from NCBI."""
    accession: str
    organism: str
    strain: str
    assembly_level: str
    total_sequence_length: int
    scaffold_count: int
    submission_date: str = ""
    is_reference: bool = False

    def __str__(self) -> str:
        ref = " [REF]" if self.is_reference else ""
        size_mb = self.total_sequence_length / 1_000_000
        return (
            f"{self.accession}  {self.organism}"
            + (f" ({self.strain})" if self.strain else "")
            + f"  {self.assembly_level}  {size_mb:.1f} Mb{ref}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _api_key() -> Optional[str]:
    return os.environ.get("NCBI_API_KEY") or None


def _rate_sleep() -> None:
    time.sleep(_RATE_WITH_KEY if _api_key() else _RATE_NO_KEY)


def _common_params() -> dict:
    p: dict = {}
    key = _api_key()
    if key:
        p["api_key"] = key
    return p


def _get_json(
    url: str,
    params: Optional[dict] = None,
    *,
    _opener: Optional[Callable] = None,
) -> dict:
    """HTTP GET → parsed JSON.  *_opener* replaces ``urllib.request.urlopen`` in tests."""
    full_params = {**(params or {}), **_common_params()}
    if full_params:
        url = url + "?" + urllib.parse.urlencode(full_params)

    opener = _opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with opener(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        raise NcbiError(f"HTTP {exc.code} — {url}: {body}") from exc
    except NcbiError:
        raise
    except Exception as exc:
        raise NcbiError(f"Request failed — {url}: {exc}") from exc


def _stream_to_file(
    url: str,
    dest: Path,
    *,
    progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    _opener: Optional[Callable] = None,
) -> Path:
    """Stream a binary URL to *dest*, calling ``progress_callback(bytes, total)``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    opener = _opener or urllib.request.urlopen
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/zip, application/octet-stream"},
    )
    try:
        with opener(req, timeout=600) as resp:
            total_raw = resp.headers.get("Content-Length")
            total = int(total_raw) if total_raw else None
            written = 0
            with dest.open("wb") as fh:
                while True:
                    chunk = resp.read(1 << 17)  # 128 KB
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    if progress_callback:
                        progress_callback(written, total)
    except urllib.error.HTTPError as exc:
        dest.unlink(missing_ok=True)
        body = exc.read().decode(errors="replace")[:500]
        raise NcbiError(f"HTTP {exc.code} downloading {url}: {body}") from exc
    except NcbiError:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise NcbiError(f"Download failed: {exc}") from exc

    # Catch silent truncations: when the server advertised a Content-Length
    # but the connection dropped early, the write loop exits cleanly.  A
    # truncated ZIP would later fail with BadZipFile far from the root cause.
    if total is not None and written != total:
        dest.unlink(missing_ok=True)
        raise NcbiError(
            f"Download truncated: expected {total} bytes, got {written}. "
            "Re-run the command to retry."
        )
    return dest


def _stream_text(
    url: str,
    *,
    progress_callback: Optional[Callable[[int], None]] = None,
    _opener: Optional[Callable] = None,
) -> str:
    """Stream a text URL, return as string."""
    opener = _opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"Accept": "text/plain"})
    try:
        with opener(req, timeout=300) as resp:
            chunks: list[bytes] = []
            total_bytes = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                chunks.append(chunk)
                total_bytes += len(chunk)
                if progress_callback:
                    progress_callback(total_bytes)
        return b"".join(chunks).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:500]
        raise NcbiError(f"HTTP {exc.code} — {url}: {body}") from exc
    except NcbiError:
        raise
    except Exception as exc:
        raise NcbiError(f"Text fetch failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Progress bar helpers (Rich if available, else no-op)
# ---------------------------------------------------------------------------

class _NoOpBar:
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def update_bytes(self, written: int, total: Optional[int]) -> None: pass
    def update_count(self, done: int) -> None: pass


class _RichBytesBar:
    def __init__(self, description: str) -> None:
        from rich.progress import (  # noqa: PLC0415
            BarColumn, DownloadColumn, Progress, SpinnerColumn,
            TextColumn, TimeElapsedColumn, TransferSpeedColumn,
        )
        self._prog = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description:<40}"),
            BarColumn(bar_width=30),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeElapsedColumn(),
        )
        self._desc = description
        self._task: Optional["TaskID"] = None

    def __enter__(self):
        self._prog.__enter__()
        self._task = self._prog.add_task(self._desc, total=None)
        return self

    def __exit__(self, *args):
        self._prog.__exit__(*args)

    def update_bytes(self, written: int, total: Optional[int]) -> None:
        if self._task is None:
            return
        self._prog.update(self._task, completed=written, total=total)

    def update_count(self, done: int) -> None:
        pass  # not used for byte progress


class _RichCountBar:
    def __init__(self, description: str, total: int) -> None:
        from rich.progress import (  # noqa: PLC0415
            BarColumn, MofNCompleteColumn, Progress,
            SpinnerColumn, TextColumn, TimeElapsedColumn,
        )
        self._prog = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description:<40}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        )
        self._desc = description
        self._total = total
        self._task: Optional["TaskID"] = None

    def __enter__(self):
        self._prog.__enter__()
        self._task = self._prog.add_task(self._desc, total=self._total)
        return self

    def __exit__(self, *args):
        self._prog.__exit__(*args)

    def update_bytes(self, written: int, total: Optional[int]) -> None:
        pass

    def update_count(self, done: int) -> None:
        if self._task is None:
            return
        self._prog.update(self._task, completed=done)


def _bytes_bar(description: str, show: bool):
    if not show:
        return _NoOpBar()
    try:
        return _RichBytesBar(description)
    except ImportError:
        return _NoOpBar()


def _count_bar(description: str, total: int, show: bool):
    if not show:
        return _NoOpBar()
    try:
        return _RichCountBar(description, total)
    except ImportError:
        return _NoOpBar()


# ---------------------------------------------------------------------------
# Genome functions
# ---------------------------------------------------------------------------

def list_genomes(
    taxon: str,
    *,
    assembly_level: Optional[str] = None,
    reference_only: bool = False,
    max_results: int = 20,
    _opener: Optional[Callable] = None,
) -> list[AssemblyInfo]:
    """Query NCBI Datasets API for genome assemblies matching *taxon*.

    Parameters
    ----------
    taxon:
        Scientific name or NCBI taxonomy ID (e.g. ``"dickeya"``, ``"2038"``).
    assembly_level:
        Filter by level: ``complete``, ``chromosome``, ``scaffold``,
        or ``contig``.  ``None`` returns all levels.
    reference_only:
        Return only reference / representative assemblies.
    max_results:
        Maximum number of assembly records to return.

    Returns
    -------
    list[AssemblyInfo]
        Assembly metadata, newest first.

    Raises
    ------
    NcbiError
        On HTTP errors or if taxon does not exist in NCBI taxonomy.
    """
    if assembly_level and assembly_level.lower() not in _LEVEL_API:
        raise NcbiError(
            f"Unknown assembly_level '{assembly_level}'. "
            f"Valid choices: {sorted(_LEVEL_API)}"
        )

    taxon_enc = urllib.parse.quote(taxon)
    url = f"{DATASETS_BASE}/genome/taxon/{taxon_enc}/dataset_report"

    params: dict = {"page_size": min(max_results, 1000)}
    if assembly_level:
        params["filters.assembly_level"] = _LEVEL_API[assembly_level.lower()]
    if reference_only:
        params["filters.reference_only"] = "true"

    assemblies: list[AssemblyInfo] = []
    page_token: Optional[str] = None

    while len(assemblies) < max_results:
        if page_token:
            params["page_token"] = page_token

        _rate_sleep()
        data = _get_json(url, params, _opener=_opener)

        for report in data.get("reports", []):
            asm   = report.get("assembly_info", {})
            org   = report.get("organism", {})
            stats = report.get("assembly_stats", {})
            assemblies.append(AssemblyInfo(
                accession=report.get("accession", ""),
                organism=org.get("organism_name", ""),
                strain=org.get("infraspecific_names", {}).get("strain", ""),
                assembly_level=asm.get("assembly_level", ""),
                total_sequence_length=int(stats.get("total_sequence_length") or 0),
                scaffold_count=int(stats.get("number_of_scaffolds") or 0),
                submission_date=asm.get("submission_date", ""),
                is_reference=asm.get("refseq_category", "") in (
                    "reference genome", "representative genome"
                ),
            ))
            if len(assemblies) >= max_results:
                break

        page_token = data.get("next_page_token")
        if not page_token or not data.get("reports"):
            break

    return assemblies


def download_genomes(
    taxon: str,
    out_dir: Path,
    *,
    assembly_level: Optional[str] = None,
    reference_only: bool = False,
    max_assemblies: int = 10,
    include: Sequence[str] = ("GENOME_FASTA",),
    progress: bool = True,
    _opener: Optional[Callable] = None,
) -> list[Path]:
    """Download genome files for assemblies matching *taxon*.

    Workflow
    --------
    1. Call :func:`list_genomes` to obtain accession numbers.
    2. Download a single ZIP from the NCBI Datasets endpoint.
    3. Extract FASTA / GFF files to *out_dir*; delete the ZIP.

    Parameters
    ----------
    taxon:
        Scientific name or NCBI taxonomy ID.
    out_dir:
        Directory where files will be written (created if absent).
    assembly_level:
        Filter: ``complete``, ``chromosome``, ``scaffold``, or ``contig``.
    reference_only:
        Download only reference / representative assemblies.
    max_assemblies:
        Hard cap — safeguard against accidentally downloading a whole genus.
        Default 10.
    include:
        Data types to include.  One or more of: ``GENOME_FASTA``,
        ``GENOME_GFF``, ``PROTEIN_FASTA``, ``RNA_FASTA``, ``GENOME_GBFF``.
    progress:
        Show a Rich progress bar.

    Returns
    -------
    list[Path]
        Extracted file paths inside *out_dir*.

    Raises
    ------
    NcbiError
        If no assemblies match, or the download / extraction fails.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Validate include types up front so a typo like 'PROTEIN_FASTA' fails
    # cleanly instead of hitting the API and getting an opaque HTTP 400.
    norm_include: list[str] = []
    for i in include:
        key = i.upper().strip()
        norm = _INCLUDE_ALIASES.get(key, key)
        if norm not in GENOME_INCLUDE_TYPES:
            raise NcbiError(
                f"Unknown --include type {i!r}.  Valid: "
                + ", ".join(GENOME_INCLUDE_TYPES)
                + (f"  (aliases: {', '.join(_INCLUDE_ALIASES)})"
                   if _INCLUDE_ALIASES else "")
            )
        norm_include.append(norm)

    log.info(f"Querying NCBI Datasets: taxon={taxon!r}  level={assembly_level}  max={max_assemblies}")
    assemblies = list_genomes(
        taxon,
        assembly_level=assembly_level,
        reference_only=reference_only,
        max_results=max_assemblies,
        _opener=_opener,
    )

    if not assemblies:
        raise NcbiError(
            f"No assemblies found for taxon '{taxon}'"
            + (f" at level '{assembly_level}'" if assembly_level else "")
            + ".  Try a broader level or check the taxon name."
        )

    accessions = [a.accession for a in assemblies]
    log.info(f"{len(accessions)} assembly(ies) selected: {accessions}")

    # Batch accessions to keep each request URL under ~4 KB.  NCBI's
    # /datasets/v2/genome/accession/{acc1,acc2,...}/download endpoint returns
    # HTTP 414 (URI Too Long) once the comma-separated accession list grows
    # past roughly 30-40 GCA-style accessions.  Splitting into chunks of 25
    # keeps us comfortably below that limit.
    BATCH = 25
    include_qs = "&".join(
        f"include_annotation_type={urllib.parse.quote(i)}" for i in norm_include
    )
    key_qs = (f"&api_key={_api_key()}" if _api_key() else "")

    zip_paths: list[Path] = []
    bar = _bytes_bar(f"Genomes — {taxon}", progress)
    with bar:
        for batch_idx, start in enumerate(range(0, len(accessions), BATCH)):
            batch = accessions[start:start + BATCH]
            acc_str = ",".join(urllib.parse.quote(a) for a in batch)
            dl_url = (
                f"{DATASETS_BASE}/genome/accession/{acc_str}/download"
                f"?hydrated=FULLY_HYDRATED&{include_qs}{key_qs}"
            )
            zip_path = out_dir / (
                f"_ncbi_{urllib.parse.quote(taxon, safe='')}_b{batch_idx:03d}.zip"
            )
            zip_paths.append(zip_path)
            log.info(
                f"Batch {batch_idx + 1}/{(len(accessions) + BATCH - 1)//BATCH}: "
                f"downloading {len(batch)} genomes"
            )
            _stream_to_file(
                dl_url, zip_path,
                progress_callback=bar.update_bytes,
                _opener=_opener,
            )

    # Extract from every batch ZIP
    extracted: list[Path] = []
    try:
        for zip_path in zip_paths:
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    name_lower = member.lower()
                    if not any(name_lower.endswith(s) for s in _EXTRACT_SUFFIXES):
                        continue

                    # Flatten: ncbi_dataset/data/{accession}/filename
                    #          → {accession}_filename
                    parts = Path(member).parts
                    fname = Path(member).name
                    if (len(parts) >= 3 and parts[0] == "ncbi_dataset"
                            and parts[1] == "data"):
                        dest_name = f"{parts[2]}_{fname}"
                    else:
                        dest_name = fname

                    # Path-traversal guard
                    dest_path = (out_dir / dest_name).resolve()
                    try:
                        dest_path.relative_to(out_dir.resolve())
                    except ValueError:
                        log.warning(
                            f"Skipping ZIP member '{member}': resolved path "
                            f"'{dest_path}' is outside output directory "
                            f"'{out_dir}'. May indicate a malicious ZIP."
                        )
                        continue

                    # Stream-copy so multi-GB genomes don't spike memory
                    with zf.open(member) as src, dest_path.open("wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                    extracted.append(dest_path)
                    log.info(f"Extracted: {dest_path.name}")
    except zipfile.BadZipFile as exc:
        raise NcbiError(
            f"Downloaded file is not a valid ZIP archive: {exc}. "
            "The download may have been truncated or corrupted. "
            "Try again or check your network connection."
        ) from exc
    except RuntimeError as exc:
        # zipfile raises RuntimeError for encrypted ZIPs
        raise NcbiError(f"ZIP extraction failed: {exc}") from exc
    finally:
        for zp in zip_paths:
            zp.unlink(missing_ok=True)

    if not extracted:
        raise NcbiError(
            f"ZIP downloaded but no files matching {_EXTRACT_SUFFIXES[:4]}... "
            f"were found.  Check the --include types."
        )

    log.info(f"Done: {len(extracted)} file(s) in {out_dir}")
    return extracted


# ---------------------------------------------------------------------------
# Protein functions
# ---------------------------------------------------------------------------

def list_proteins(
    taxon: str,
    *,
    filter_term: str = "refseq[filter]",
    preview_size: int = 10,
    _opener: Optional[Callable] = None,
) -> tuple[int, list[dict]]:
    """Count and preview protein records for *taxon* in NCBI protein database.

    Parameters
    ----------
    taxon:
        Scientific name (e.g. ``"dickeya"``).
    filter_term:
        Extra Entrez query filter.  Default ``refseq[filter]`` returns only
        RefSeq proteins (fewer, higher quality).  Use ``""`` for all records.
    preview_size:
        Number of record summaries to fetch for preview.

    Returns
    -------
    tuple[int, list[dict]]
        ``(total_count, preview_records)`` — each record has keys
        ``uid``, ``title``, ``organism``, ``length``.
    """
    term = f"{taxon}[organism]"
    if filter_term:
        term += f" AND {filter_term}"

    _rate_sleep()
    search_params: dict = {
        "db": "protein",
        "term": term,
        "retmax": str(preview_size),
        "retmode": "json",
        "usehistory": "y",
    }
    data = _get_json(f"{EUTILS_BASE}/esearch.fcgi", search_params, _opener=_opener)
    result = data.get("esearchresult", {})
    total = int(result.get("count", 0))
    ids   = result.get("idlist", [])

    if not ids:
        return total, []

    # Fetch summaries for preview display
    _rate_sleep()
    sum_data = _get_json(
        f"{EUTILS_BASE}/esummary.fcgi",
        {"db": "protein", "id": ",".join(ids), "retmode": "json"},
        _opener=_opener,
    )

    records: list[dict] = []
    for uid in ids:
        entry = sum_data.get("result", {}).get(uid, {})
        records.append({
            "uid":      uid,
            "title":    entry.get("title", ""),
            "organism": entry.get("organism", ""),
            "length":   int(entry.get("slen", 0) or 0),
        })

    return total, records


def download_proteins(
    taxon: str,
    out_dir: Path,
    *,
    filter_term: str = "refseq[filter]",
    max_results: int = 500,
    progress: bool = True,
    _opener: Optional[Callable] = None,
) -> Path:
    """Download protein sequences for *taxon* to a multi-FASTA file.

    Uses NCBI Entrez ``esearch`` + ``efetch`` (batched, 500 per request) so
    very large result sets are streamed efficiently.

    The resulting ``.faa`` file is suitable for use as:
    * **BRAKER3** ``--proteins`` evidence input
    * **MAKER** ``protein`` hint track
    * **DIAMOND** or **MMseqs2** reference database

    Parameters
    ----------
    taxon:
        Scientific name (e.g. ``"dickeya"``, ``"pectobacteriaceae"``).
    out_dir:
        Directory where the FASTA file will be written.
    filter_term:
        Extra Entrez filter.  Default ``refseq[filter]``.
        Use ``""`` for all records — may be very large.
    max_results:
        Maximum protein sequences to download.
    progress:
        Show a Rich progress bar.

    Returns
    -------
    Path
        ``out_dir/<taxon_slug>_proteins.faa``

    Raises
    ------
    NcbiError
        If no proteins are found or the download fails.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    slug     = taxon.lower().replace(" ", "_").replace("/", "_")
    out_path = out_dir / f"{slug}_proteins.faa"

    term = f"{taxon}[organism]"
    if filter_term:
        term += f" AND {filter_term}"
    log.info(f"Entrez protein search: {term!r}")

    # Phase 1 — esearch with usehistory
    _rate_sleep()
    search_data = _get_json(
        f"{EUTILS_BASE}/esearch.fcgi",
        {
            "db": "protein", "term": term,
            "retmax": "0", "retmode": "json", "usehistory": "y",
        },
        _opener=_opener,
    )
    result    = search_data.get("esearchresult", {})
    total     = int(result.get("count", 0))
    web_env   = result.get("webenv", "")
    query_key = result.get("querykey", "1")

    if total == 0:
        raise NcbiError(
            f"No proteins found for '{taxon}'"
            + (f" with filter '{filter_term}'" if filter_term else "")
            + ".  Try a broader taxon or remove the filter."
        )

    actual = min(total, max_results)
    log.info(f"Found {total} proteins — downloading {actual}")

    # Phase 2 — efetch in batches of 500
    _BATCH = 500
    base_fetch = (
        f"{EUTILS_BASE}/efetch.fcgi"
        f"?db=protein&query_key={query_key}&WebEnv={web_env}"
        f"&rettype=fasta&retmode=text"
    )
    if _api_key():
        base_fetch += f"&api_key={_api_key()}"

    bar = _count_bar(f"Proteins — {taxon}", actual, progress)

    try:
        with out_path.open("w", encoding="utf-8") as fh, bar:
            fetched = 0
            while fetched < actual:
                batch = min(_BATCH, actual - fetched)
                _rate_sleep()
                fetch_url = f"{base_fetch}&retstart={fetched}&retmax={batch}"
                text = _stream_text(fetch_url, _opener=_opener)
                fh.write(text)
                fetched += batch
                bar.update_count(fetched)
    except NcbiError:
        out_path.unlink(missing_ok=True)
        raise

    log.info(f"Protein FASTA written: {out_path}  ({actual} sequences)")
    return out_path
