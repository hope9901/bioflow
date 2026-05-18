"""Reference database management — fetch, list, verify.

``bioflow db fetch <name> --dest /refs``  downloads a reference database with
a Rich progress bar.  Databases are registered in ``_DB_CATALOG`` below.

Design goals
------------
* No extra dependencies beyond stdlib + rich (already a dep).
* Resumable: if the destination file already exists and passes the MD5 check,
  the download is skipped.
* Streaming download with progress: uses ``urllib.request`` + ``rich.progress``.
* Decompression is left to the user (or a future flag) because many DBs are
  intentionally stored compressed.

Adding a new DB
---------------
Append an entry to ``_DB_CATALOG`` — the dict key is the name used on the CLI.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from bioflow.core.logger import get_logger

log = get_logger()

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

_DB_CATALOG: dict[str, dict] = {
    "eggnog": {
        "name": "eggNOG v5.0 — annotation database",
        "url": (
            "http://eggnog5.embl.de/download/emapperdb-5.0.2/eggnog.db.gz"
        ),
        "size_gb": 8.5,
        "md5": None,           # large file — skip checksum by default
        "dest_file": "eggnog/eggnog.db.gz",
        "used_by": ["eggnog_mapper"],
        "notes": "Run emapper-download-data after fetching.",
    },
    "pfam": {
        "name": "Pfam-A 36.0 — protein family HMMs",
        "url": (
            "https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/"
            "Pfam-A.hmm.gz"
        ),
        "size_gb": 0.5,
        "md5": None,
        "dest_file": "pfam/Pfam-A.hmm.gz",
        "used_by": ["interproscan"],
        "notes": "Decompress and run hmmpress before use.",
    },
    "dfam_curated": {
        "name": "Dfam 3.8 — curated repeat library",
        "url": (
            "https://dfam.org/releases/current/families/Dfam_curatedonly.h5.gz"
        ),
        "size_gb": 2.0,
        "md5": None,
        "dest_file": "dfam/Dfam_curatedonly.h5.gz",
        "used_by": ["repeatmasker", "earlgrey"],
        "notes": "Used by RepeatMasker / EarlGrey for masking.",
    },
    "busco_bacteria": {
        "name": "BUSCO bacteria_odb10 lineage",
        "url": (
            "https://busco-data.ezlab.org/v5/data/lineages/"
            "bacteria_odb10.2024-01-08.tar.gz"
        ),
        "size_gb": 0.07,
        "md5": None,
        "dest_file": "busco/bacteria_odb10.tar.gz",
        "used_by": ["busco"],
        "notes": "Extract to busco_downloads/lineages/bacteria_odb10.",
    },
    "busco_insecta": {
        "name": "BUSCO insecta_odb10 lineage",
        "url": (
            "https://busco-data.ezlab.org/v5/data/lineages/"
            "insecta_odb10.2024-01-08.tar.gz"
        ),
        "size_gb": 0.08,
        "md5": None,
        "dest_file": "busco/insecta_odb10.tar.gz",
        "used_by": ["busco"],
        "notes": "Extract to busco_downloads/lineages/insecta_odb10.",
    },
    "busco_vertebrata": {
        "name": "BUSCO vertebrata_odb10 lineage",
        "url": (
            "https://busco-data.ezlab.org/v5/data/lineages/"
            "vertebrata_odb10.2021-02-19.tar.gz"
        ),
        "size_gb": 0.3,
        "md5": None,
        "dest_file": "busco/vertebrata_odb10.tar.gz",
        "used_by": ["busco"],
    },
    "uniprot_sprot": {
        "name": "UniProt Swiss-Prot (protein sequences)",
        "url": (
            "https://ftp.uniprot.org/pub/databases/uniprot/current_release/"
            "knowledgebase/complete/uniprot_sprot.fasta.gz"
        ),
        "size_gb": 0.25,
        "md5": None,
        "dest_file": "uniprot/uniprot_sprot.fasta.gz",
        "used_by": ["braker3"],
        "notes": "Decompress before use with BRAKER3.",
    },
    "kraken2_standard_8gb": {
        "name": "Kraken2 Standard 8GB (capped) — taxonomic classifier DB",
        "url": (
            "https://genome-idx.s3.amazonaws.com/kraken/"
            "k2_standard_08gb_20240605.tar.gz"
        ),
        "size_gb": 7.5,
        "md5": None,
        "dest_file": "kraken2/k2_standard_08gb.tar.gz",
        "used_by": ["kraken2", "bracken"],
        "notes": (
            "Untar into a directory and point --kraken2-db at it.  "
            "The 8GB cap fits most workstations; replace with the full "
            "k2_standard_20240605 (~70GB) for higher sensitivity."
        ),
    },
    "10x_whitelist_v3": {
        "name": "10x Genomics 3' v3 chemistry barcode whitelist (3M)",
        "url": (
            "https://github.com/10XGenomics/cellranger/raw/"
            "master/lib/python/cellranger/barcodes/3M-february-2018.txt.gz"
        ),
        "size_gb": 0.02,
        "md5": None,
        "dest_file": "10x/3M-february-2018.txt.gz",
        "used_by": ["starsolo", "cellranger"],
        "notes": (
            "Gunzip to a plain .txt before passing to STARsolo's "
            "--soloCBwhitelist."
        ),
    },
    "bowtie2_grch38_noalt": {
        "name": "Bowtie2 prebuilt index — GRCh38 (no alt contigs)",
        "url": (
            "https://genome-idx.s3.amazonaws.com/bt/GRCh38_noalt_as.zip"
        ),
        "size_gb": 3.5,
        "md5": None,
        "dest_file": "bowtie2/GRCh38_noalt_as.zip",
        "used_by": ["bowtie2"],
        "notes": (
            "Unzip to reveal the index prefix files.  Pass the prefix "
            "(e.g. /refs/bowtie2/GRCh38_noalt_as) to --bowtie2-index."
        ),
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_dbs() -> list[dict]:
    """Return all catalog entries as a list of dicts (name, size_gb, used_by)."""
    rows = []
    for key, entry in _DB_CATALOG.items():
        rows.append({
            "key":     key,
            "name":    entry["name"],
            "size_gb": entry["size_gb"],
            "used_by": entry["used_by"],
            "notes":   entry.get("notes", ""),
        })
    return rows


def fetch_db(
    name: str,
    dest_root: Path,
    *,
    skip_if_exists: bool = True,
    _opener=None,           # injection point for tests
) -> Path:
    """Download database *name* to ``dest_root/<dest_file>``.

    Parameters
    ----------
    name:
        Catalog key (e.g. ``"busco_bacteria"``).
    dest_root:
        Root directory under which the file will be placed.
    skip_if_exists:
        When ``True`` (default) and the destination file already exists,
        the download is skipped immediately.
    _opener:
        Optional callable ``(url) -> file-like`` for testing without network.

    Returns
    -------
    Path
        The absolute path of the (possibly already-existing) downloaded file.

    Raises
    ------
    KeyError
        When *name* is not in the catalog.
    RuntimeError
        On network / write errors.
    """
    if name not in _DB_CATALOG:
        raise KeyError(
            f"Unknown database '{name}'. "
            f"Available: {', '.join(_DB_CATALOG)}"
        )
    entry = _DB_CATALOG[name]
    dest = dest_root / entry["dest_file"]

    if skip_if_exists and dest.exists():
        log.info(f"DB '{name}' already present at {dest} — skipping download.")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = entry["url"]
    size_gb = entry.get("size_gb", 0)

    log.info(f"Fetching '{name}' ({size_gb:.2f} GB) from {url}")

    try:
        from rich.progress import (  # noqa: PLC0415, F401
            BarColumn,
            DownloadColumn,
            Progress,
            TextColumn,
            TimeRemainingColumn,
            TransferSpeedColumn,
        )
        _rich_available = True
    except ImportError:
        _rich_available = False

    opener = _opener or urllib.request.urlopen

    try:
        response = opener(url)
        total = int(response.headers.get("Content-Length", 0) or 0)

        if _rich_available and total:
            _download_with_rich(response, dest, total, name)
        else:
            _download_plain(response, dest)
    except Exception as exc:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"Failed to download '{name}': {exc}") from exc

    # Validate downloaded size against Content-Length (when header was present)
    if total and dest.exists():
        actual_size = dest.stat().st_size
        if actual_size != total:
            dest.unlink()
            raise RuntimeError(
                f"Download of '{name}' appears truncated: "
                f"expected {total} bytes but received {actual_size} bytes. "
                "Re-run 'bioflow db fetch' to retry."
            )

    # Optional MD5 verify
    expected_md5 = entry.get("md5")
    if expected_md5:
        actual = _md5(dest)
        if actual != expected_md5:
            dest.unlink()
            raise RuntimeError(
                f"MD5 mismatch for '{name}': expected {expected_md5}, got {actual}"
            )
        log.info(f"MD5 verified for '{name}'")

    log.info(f"'{name}' downloaded to {dest}")
    return dest


def verify_db(name: str, dest_root: Path) -> bool:
    """Return True if *name* exists and passes its MD5 checksum.

    When no MD5 is catalogued, only file existence is checked.
    """
    if name not in _DB_CATALOG:
        raise KeyError(f"Unknown database '{name}'.")
    entry = _DB_CATALOG[name]
    dest = dest_root / entry["dest_file"]

    if not dest.exists():
        log.warning(f"DB '{name}' not found at {dest}")
        return False

    expected_md5 = entry.get("md5")
    if not expected_md5:
        log.info(f"DB '{name}' present (no checksum registered).")
        return True

    actual = _md5(dest)
    if actual == expected_md5:
        log.info(f"DB '{name}' checksum OK.")
        return True

    log.warning(f"DB '{name}' checksum MISMATCH: expected {expected_md5}, got {actual}")
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CHUNK = 65536   # 64 KiB


def _download_plain(response, dest: Path) -> None:
    with dest.open("wb") as fh:
        while True:
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            fh.write(chunk)


def _download_with_rich(response, dest: Path, total: int, label: str) -> None:
    from rich.progress import (  # noqa: PLC0415
        BarColumn, DownloadColumn, Progress,
        TextColumn, TimeRemainingColumn, TransferSpeedColumn,
    )
    with Progress(
        TextColumn(f"[bold cyan]{label}"),
        BarColumn(bar_width=40),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ) as prog:
        task = prog.add_task("downloading", total=total)
        with dest.open("wb") as fh:
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                prog.advance(task, len(chunk))


def _md5(path: Path, block_size: int = 2**20) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(block_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()
