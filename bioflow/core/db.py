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

import functools
import hashlib
import os
import re
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
        # ── functional-annotation DB versioning ──
        "version": "5.0.2",
        # Provisioned *inside* the eggnog-mapper container so the DB matches the
        # tool build; {dir} is bind-mounted from the refs root.
        "provision": "download_eggnog_data.py -y --data_dir {dir}",
        # Cheap version probe (no multi-GB download): the emapperdb dir is
        # named emapperdb-<ver>; scrape the download index for the newest.
        "latest": {"url": "http://eggnog5.embl.de/download/",
                   "regex": r"emapperdb-([0-9][0-9.]*)"},
    },
    "pfam": {
        "name": "Pfam-A 38.2 — protein family HMMs",
        "url": (
            "https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/"
            "Pfam-A.hmm.gz"
        ),
        "size_gb": 0.5,
        "md5": None,
        "dest_file": "pfam/Pfam-A.hmm.gz",
        "used_by": ["interproscan", "pfam_scan"],
        "notes": "Decompress and run hmmpress before use.",
        "version": "38.2",
        "provision": "sh -c 'cd {dir} && wget -q "
                     "https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/Pfam-A.hmm.gz "
                     "&& gunzip -f Pfam-A.hmm.gz && hmmpress -f Pfam-A.hmm'",
        "latest": {"url": "https://ftp.ebi.ac.uk/pub/databases/Pfam/current_release/relnotes.txt",
                   "regex": r"RELEASE\s+([0-9]+\.[0-9]+)"},
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
        "genome": "hg38",
        "asset": "bowtie2_index",
        "notes": (
            "Unzip to reveal the index prefix files.  Pass the prefix "
            "(e.g. /refs/bowtie2/GRCh38_noalt_as) to --bowtie2-index."
        ),
    },
    # ── Variant-calling known sites (GATK best practices) ──────────────────
    "dbsnp_grch38": {
        "name": "dbSNP 138 — GRCh38 known SNP sites (GATK bundle)",
        "url": (
            "https://storage.googleapis.com/genomics-public-data/resources/"
            "broad/hg38/v0/Homo_sapiens_assembly38.dbsnp138.vcf.gz"
        ),
        "size_gb": 1.6,
        "md5": None,
        "dest_file": "gatk/hg38/Homo_sapiens_assembly38.dbsnp138.vcf.gz",
        "used_by": ["gatk4"],
        "genome": "hg38",
        "asset": "dbsnp",
        "notes": (
            "Known-sites VCF for GATK BQSR / VQSR.  Also fetch its .tbi "
            "(same URL + .tbi) or index with `gatk IndexFeatureFile`."
        ),
    },
    "mills_indels_grch38": {
        "name": "Mills & 1000G gold-standard indels — GRCh38 (GATK bundle)",
        "url": (
            "https://storage.googleapis.com/genomics-public-data/resources/"
            "broad/hg38/v0/Mills_and_1000G_gold_standard.indels.hg38.vcf.gz"
        ),
        "size_gb": 0.02,
        "md5": None,
        "dest_file": "gatk/hg38/Mills_and_1000G_gold_standard.indels.hg38.vcf.gz",
        "used_by": ["gatk4"],
        "genome": "hg38",
        "asset": "known_indels",
        "notes": "Known-indels VCF for GATK BQSR.  Fetch the .tbi alongside.",
    },
    # ── Epigenomics ────────────────────────────────────────────────────────
    "encode_blacklist_grch38": {
        "name": "ENCODE blacklist v2 — GRCh38 problematic regions",
        "url": (
            "https://github.com/Boyle-Lab/Blacklist/raw/master/lists/"
            "hg38-blacklist.v2.bed.gz"
        ),
        "size_gb": 0.001,
        "md5": None,
        "dest_file": "encode/hg38-blacklist.v2.bed.gz",
        "used_by": ["macs3", "tobias", "deeptools"],
        "genome": "hg38",
        "asset": "blacklist",
        "notes": (
            "Gunzip and pass to peak callers / coverage tools to exclude "
            "ENCODE blacklisted regions (ChIP-seq / ATAC-seq)."
        ),
    },
    # ── Transcriptome annotation ───────────────────────────────────────────
    "gencode_grch38": {
        "name": "GENCODE v46 — GRCh38 comprehensive gene annotation (GTF)",
        "url": (
            "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/"
            "release_46/gencode.v46.annotation.gtf.gz"
        ),
        "size_gb": 0.05,
        "md5": None,
        "dest_file": "gencode/gencode.v46.annotation.gtf.gz",
        "used_by": ["star", "salmon", "subread", "stringtie"],
        "genome": "hg38",
        "asset": "ensembl_gtf",
        "notes": (
            "Gene model GTF for STAR / Salmon (tximport) / featureCounts. "
            "Pair with the matching GRCh38 primary-assembly FASTA."
        ),
    },
    # ── Gene functional-annotation databases ───────────────────────────────
    # These are provisioned *inside* the annotating tool's own container (the
    # BioContainer ships the downloader but not the multi-GB data), so the DB
    # build always matches the pinned tool.  `bioflow db provision <name>`
    # pulls the tool image + runs `provision`; `bioflow db update <name>` only
    # re-downloads when `latest` reports a newer version than the marker.
    "dbcan": {
        "name": "dbCAN — CAZyme annotation database",
        "url": "",                       # provisioned via the container downloader
        "size_gb": 7.0,
        "md5": None,
        "dest_file": "dbcan",
        "used_by": ["dbcan"],
        "version": "14",
        "provision": "dbcan_build --cpus 4 --db-dir {dir} --clean",
        # The download page now phrases releases as "HMMdb v14"; the old
        # "dbCAN-HMMdb-V<n>" file-listing format is matched too (kept lenient).
        "latest": {"url": "https://bcb.unl.edu/dbCAN2/download/Databases/",
                   "regex": r"HMMdb[- ]?[vV]([0-9]+)"},
        "notes": "CAZy HMMs + CGC/substrate data for run_dbCAN.",
    },
    "antismash_db": {
        "name": "antiSMASH — BGC detection databases",
        "url": "",
        "size_gb": 9.0,
        "md5": None,
        "dest_file": "antismash",
        "used_by": ["antismash"],
        "version": "8.0",
        "provision": "download-antismash-databases --database-dir {dir}",
        # The DB series tracks the antiSMASH major.minor release; probe the
        # official release index for the newest one.
        "latest": {"url": "https://dl.secondarymetabolites.org/releases/",
                   "regex": r"([0-9]+\.[0-9]+)\.[0-9]+/"},
        "notes": "PFAM/ClusterBlast/Resfams data for antiSMASH.",
    },
    "gtdbtk_r232": {
        "name": "GTDB-Tk reference data — release R232",
        # GTDB-Tk pins the release its own download-db.sh fetches: gtdbtk 2.7.2
        # requires r232 (confirmed from the tool's download-db.sh: release232 /
        # gtdbtk_r232_data), so the DB must match the tool, not just "latest".
        "url": (
            "https://data.gtdb.ecogenomic.org/releases/release232/232.0/"
            "auxillary_files/gtdbtk_package/full_package/gtdbtk_r232_data.tar.gz"
        ),
        "size_gb": 110.0,
        "md5": None,
        "dest_file": "gtdbtk/gtdbtk_r232_data.tar.gz",
        "used_by": ["gtdbtk"],
        "version": "r232",
        "provision": "sh -c 'tar xzf {dir}/gtdbtk_r232_data.tar.gz -C {dir}'",
        "latest": {"url": "https://data.gtdb.ecogenomic.org/releases/latest/VERSION.txt",
                   "regex": r"(r?\d+(?:\.\d+)?)"},
        "notes": "Set GTDBTK_DATA_PATH to the extracted release_* directory.",
    },
    "kofam": {
        "name": "KOfam — KEGG Orthology HMM profiles + ko_list (KofamScan)",
        "url": "https://www.genome.jp/ftp/db/kofam/profiles.tar.gz",
        "size_gb": 3.0,
        "md5": None,
        "dest_file": "kofam/profiles.tar.gz",
        "used_by": ["kofamscan"],
        "version": "2026-06-30",
        "provision": "sh -c 'cd {dir} && wget -q https://www.genome.jp/ftp/db/kofam/ko_list.gz "
                     "https://www.genome.jp/ftp/db/kofam/profiles.tar.gz "
                     "&& gunzip -f ko_list.gz && tar xzf profiles.tar.gz'",
        # The version is the date the ``profiles.tar.gz`` the URL serves was last
        # published (README itself is a stale 2019 file, so don't scrape that).
        "latest": {"url": "https://www.genome.jp/ftp/db/kofam/",
                   "regex": r"profiles\.tar\.gz.*?(\d{4}-\d{2}-\d{2})"},
        "notes": "KEGG KO assignment via exec_annotation (KofamScan).",
    },
    "dram": {
        "name": "DRAM — metabolism databases (KEGG/UniRef/Pfam/dbCAN/MEROPS/VOGDB)",
        "url": "",
        "size_gb": 30.0,
        "md5": None,
        "dest_file": "dram",
        "used_by": ["dram"],
        "version": "1.5",
        "provision": "DRAM-setup.py prepare_databases --output_dir {dir} "
                     "--skip_uniref --threads 8",
        # DRAM's DBs are built by the tool; track its major.minor on PyPI.
        "latest": {"url": "https://pypi.org/pypi/DRAM-bio/json",
                   "regex": r'"([0-9]+\.[0-9]+)\.[0-9]+"'},
        "notes": "MAG/genome metabolic annotation.  Add --uniref for the full "
                 "(~500 GB) build; omit it for the lean profile.",
    },
    "funannotate_db": {
        "name": "funannotate — fungal annotation databases",
        "url": "",
        "size_gb": 20.0,
        "md5": None,
        "dest_file": "funannotate",
        "used_by": ["funannotate"],
        "version": "2024-01",
        "provision": "funannotate setup -d {dir} -b all",
        # No probe: `funannotate setup` date-stamps the DB (e.g. 2024-01), which
        # has no clean upstream index to scrape (the tool's own semver on PyPI is
        # a different versioning scheme, so it can't stand in for the DB date).
        "latest": None,
        "notes": "InterPro/Pfam/dbCAN/MEROPS/UniProt data for `funannotate annotate`.",
    },
    "vep_cache": {
        "name": "Ensembl VEP cache — GRCh38 (release 116)",
        "url": "",
        "size_gb": 25.0,
        "md5": None,
        "dest_file": "vep",
        "used_by": ["ensembl_vep"],
        "version": "116",
        "provision": "vep_install --AUTO cf --SPECIES homo_sapiens "
                     "--ASSEMBLY GRCh38 --CACHEDIR {dir} --NO_HTSLIB",
        "latest": {"url": "https://ftp.ensembl.org/pub/",
                   "regex": r"release-(\d+)"},
        "notes": "Offline annotation cache for `vep --cache --dir_cache`.",
    },
    "checkm2_db": {
        "name": "CheckM2 — DIAMOND reference database (UniRef100/KO)",
        "url": "",
        "size_gb": 3.0,
        "md5": None,
        "dest_file": "checkm2",
        "used_by": ["checkm2"],
        # Confirmed from the pinned Zenodo record (5571251): the CheckM2
        # reference DB is release "2", not the tool's own 1.x version.
        "version": "2",
        "provision": "checkm2 database --download --path {dir}",
        "latest": None,
        "notes": "Completeness/contamination model DB for `checkm2 predict`.",
    },
    "bakta_db": {
        "name": "Bakta — bacterial annotation database (light)",
        "url": "",
        "size_gb": 4.0,
        "md5": None,
        "dest_file": "bakta",
        "used_by": ["bakta"],
        # Schema/release confirmed from the downloaded db-light/version.json:
        # {"major": 6, "minor": 0, "date": "2025-02-24", "type": "light"}.
        "version": "6.0",
        # `light` (~4 GB on disk) is the default here: the `full` profile is
        # ~75 GB, which is more than most workstations can spare just to
        # annotate a genome.  Swap in `--type full` for the deeper PSC/UniRef
        # hits when you have the space.
        "provision": "bakta_db download --output {dir} --type light",
        "latest": None,
        "notes": "AMRFinderPlus/PSC/UniRef data for `bakta`.  Downloads into "
                 "<dir>/db-light — point the recipe's bakta_db at that path.",
    },
    "metaphlan": {
        "name": "MetaPhlAn — CHOCOPhlAnSGB marker database + Bowtie2 index",
        "url": "",
        "size_gb": 48.0,
        "md5": None,
        "dest_file": "metaphlan",
        "used_by": ["metaphlan4"],
        # Confirmed from the biobakery mirror's mpa_latest pointer.
        "version": "vJan26_CHOCOPhlAnSGB_202605",
        # `metaphlan --install` pulls the marker tar (~6 GB) + the prebuilt
        # Bowtie2 index (~42 GB) into {dir}; ~90 GB unpacked, so provision it on
        # a roomy volume.  --db_dir points the profiler at it (the 4.2 rename of
        # --bowtie2db).
        "provision": "metaphlan --install --db_dir {dir}",
        "latest": {"url": "http://cmprod1.cibio.unitn.it/biobakery4/"
                          "metaphlan_databases/mpa_latest",
                   "regex": r"(v\w+_CHOCOPhlAnSGB_\d+)"},
        "notes": "Marker-gene DB for `metaphlan --db_dir`.  Large: ~48 GB "
                 "download, ~90 GB unpacked.",
    },
    "dfast_db": {
        "name": "DFAST — reference protein databases",
        "url": "",
        "size_gb": 2.0,
        "md5": None,
        "dest_file": "dfast",
        "used_by": ["dfast"],
        "version": "1.4",
        "provision": "dfast_file_downloader.py --protein dfast --dbroot {dir}",
        "latest": None,
        "notes": "Reference proteins/HMMs for `dfast` structural+functional annotation.",
    },
}


# Cache the upstream "latest version" probe per DB for the life of the process,
# so a fan-out pipeline that runs the same annotation tool many times only hits
# the network once (the run-time hook calls this on every stage).
_LATEST_CACHE: "dict[str, str | None]" = {}


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
            "genome":  entry.get("genome"),
            "asset":   entry.get("asset"),
            "notes":   entry.get("notes", ""),
        })
    return rows


def refgenie_manifest(dest_root: Path | None = None) -> dict:
    """Export the catalog as a refgenie-compatible asset manifest.

    `refgenie <https://refgenie.databio.org/>`_ organises references as
    ``<genome>/<asset>`` paths.  bioflow is not a refgenie server, but it
    can emit a manifest that maps each catalogued DB onto refgenie's
    genome/asset namespace so a lab already standardised on refgenie can
    see, at a glance, which of its existing assets satisfy a bioflow
    requirement (and where bioflow would place a freshly-fetched copy).

    Only entries carrying ``genome`` + ``asset`` keys are emitted (the
    organism-agnostic DBs like Pfam / eggNOG have no refgenie genome).

    Returns a dict shaped like::

        {
          "genomes": {
            "hg38": {
              "assets": {
                "dbsnp":    {"bioflow_db": "dbsnp_grch38", "path": "...", "used_by": [...]},
                "blacklist":{...},
                ...
              }
            }
          }
        }
    """
    genomes: dict[str, dict] = {}
    for key, entry in _DB_CATALOG.items():
        genome = entry.get("genome")
        asset = entry.get("asset")
        if not (genome and asset):
            continue
        path = entry["dest_file"]
        if dest_root is not None:
            path = str((Path(dest_root) / path).resolve())
        genomes.setdefault(genome, {"assets": {}})["assets"][asset] = {
            "bioflow_db": key,
            "path": path,
            "size_gb": entry.get("size_gb"),
            "used_by": entry.get("used_by", []),
        }
    return {"refgenie_compatible": True, "genomes": genomes}


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

    # Stamp the installed version so version-gated updates can compare later.
    if catalog_version(name):
        write_db_version(name, dest_root)

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
# DB versioning + version-gated updates (functional-annotation databases)
# ---------------------------------------------------------------------------
#
# The annotation DBs are too large to bundle and change on their own release
# cadence, so we track a *version* per DB and only re-download when upstream is
# newer than the copy on disk.  The installed version is recorded in a tiny
# marker file next to the data; the "latest" version is a cheap HTTP probe
# (never the multi-GB payload).

_VERSION_MARKER = ".bioflow_db_version"


def _db_top_dir(name: str) -> str:
    """First path component of the DB's dest_file (its on-disk root)."""
    return Path(_DB_CATALOG[name]["dest_file"]).parts[0]


def catalog_version(name: str) -> "str | None":
    """The DB version pinned in the catalog, or None if unversioned."""
    return _DB_CATALOG.get(name, {}).get("version")


def dbs_for_tool(tool_id: str) -> "list[str]":
    """Catalog keys of every *versioned* DB a tool consumes (in catalog order)."""
    return [k for k, e in _DB_CATALOG.items()
            if tool_id in e.get("used_by", []) and e.get("version")]


def installed_db_version(name: str, dest_root: Path) -> "str | None":
    """Read the version marker written at fetch/provision time, or None."""
    if name not in _DB_CATALOG:
        raise KeyError(f"Unknown database '{name}'.")
    marker = dest_root / _db_top_dir(name) / _VERSION_MARKER
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip() or None
    return None


def write_db_version(name: str, dest_root: Path, version: "str | None" = None) -> Path:
    """Stamp the installed DB version (defaults to the catalog version)."""
    version = version or catalog_version(name) or ""
    marker = dest_root / _db_top_dir(name) / _VERSION_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(version + "\n", encoding="utf-8")
    return marker


def _vt(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or ""))


def latest_db_version(name: str, *, _fetch=None) -> "str | None":
    """Best-effort probe of the newest available version for *name*.

    Fetches the DB's ``latest`` spec (a small index/relnotes URL, never the
    data) and returns the highest version matched by its regex.  Returns None
    when the DB has no probe or the network is unavailable — callers treat an
    unknown latest as "no update" rather than forcing a download.
    """
    spec = _DB_CATALOG.get(name, {}).get("latest")
    if not spec:
        return None
    # Real-network probes are cached process-wide; injected _fetch (tests)
    # bypasses the cache so it stays deterministic.
    if _fetch is None and name in _LATEST_CACHE:
        return _LATEST_CACHE[name]
    fetch = _fetch or (lambda u: urllib.request.urlopen(u, timeout=15)
                       .read().decode("utf-8", "replace"))
    try:
        body = fetch(spec["url"])
    except Exception as exc:            # offline / server hiccup — stay silent
        log.debug(f"latest_db_version({name}) probe failed: {exc}")
        result = None
    else:
        matches = re.findall(spec["regex"], body, re.S)
        result = max(matches, key=_vt) if matches else None
    if _fetch is None:
        _LATEST_CACHE[name] = result
    return result


def db_status(name: str, dest_root: Path, *, check_latest: bool = False,
              _fetch=None) -> dict:
    """Installed vs catalog vs (optionally) upstream-latest for one DB.

    ``update_available`` is True only when a *newer* version than the one on
    disk is known — so a routine run never re-downloads an up-to-date DB.
    """
    if name not in _DB_CATALOG:
        raise KeyError(f"Unknown database '{name}'.")
    installed = installed_db_version(name, dest_root)
    pinned = catalog_version(name)
    latest = latest_db_version(name, _fetch=_fetch) if check_latest else None
    reference = latest or pinned
    update = bool(installed and reference and _vt(reference) > _vt(installed))
    return {
        "db": name,
        "installed": installed,
        "catalog": pinned,
        "latest": latest,
        "present": installed is not None,
        "update_available": update,
    }


def provision_command(name: str, dest_root: Path) -> "str | None":
    """The shell command that builds/downloads DB *name* into ``dest_root``.

    Runs *inside the consuming tool's container* (the BioContainer ships the
    downloader, not the data), with ``{dir}`` bound to the DB's on-disk root.
    Returns None for DBs fetched via a plain URL (use ``fetch_db``).
    """
    entry = _DB_CATALOG.get(name)
    if not entry or not entry.get("provision"):
        return None
    target = (dest_root / _db_top_dir(name)).resolve()
    return entry["provision"].format(dir=target)


def ensure_db_current(tool_id: str, dest_root: Path, *, auto_update: bool = True,
                      check_latest: bool = True, _fetch=None) -> "list[dict]":
    """Run-time gate: for every DB *tool_id* uses, check the version first and
    update **only when a newer one exists** — the check is cheap and runs each
    time, the download does not (an up-to-date DB is a no-op).

    Returns a status dict per DB.  ``auto_update=True`` (default) refreshes a
    stale DB in place before the tool runs; pass ``auto_update=False`` to only
    *flag* that a newer DB is available and leave the fetch to an explicit
    ``bioflow db update``.
    """
    statuses = []
    for name in dbs_for_tool(tool_id):
        st = db_status(name, dest_root, check_latest=check_latest, _fetch=_fetch)
        if not st["present"]:
            log.warning(
                f"DB '{name}' for {tool_id} is not provisioned — run "
                f"`bioflow db provision {name} --dest {dest_root}`."
            )
        elif st["update_available"]:
            newer = st["latest"] or st["catalog"]
            if auto_update:
                log.info(f"DB '{name}': {st['installed']} -> {newer}; updating.")
                update_db(name, dest_root, _fetch=_fetch)
            else:
                log.warning(
                    f"DB '{name}' for {tool_id}: newer version {newer} available "
                    f"(installed {st['installed']}). Run "
                    f"`bioflow db update {name}` to refresh."
                )
        statuses.append(st)
    return statuses


def update_db(name: str, dest_root: Path, *, _fetch=None) -> dict:
    """Version-gated refresh: fetch + re-stamp only when upstream is newer.

    A no-op (with ``updated=False``) when the on-disk DB is already current, so
    it is safe to call on a schedule.
    """
    st = db_status(name, dest_root, check_latest=True, _fetch=_fetch)
    if st["present"] and not st["update_available"]:
        log.info(f"DB '{name}' already current ({st['installed']}).")
        return {**st, "updated": False}
    # A URL-backed DB can be fetched here; a provision-only DB must be rebuilt
    # in its tool container via `bioflow db provision`.
    if _DB_CATALOG[name].get("url"):
        fetch_db(name, dest_root, skip_if_exists=False)
    target_version = st["latest"] or st["catalog"]
    write_db_version(name, dest_root, target_version)
    log.info(f"DB '{name}' updated to {target_version}.")
    return {**st, "installed": target_version, "updated": True}


# ---------------------------------------------------------------------------
# Run-time hook: keep a stage's DBs current just before it runs
# ---------------------------------------------------------------------------

REFS_ENV = "BIOFLOW_REFS"


@functools.lru_cache(maxsize=1)
def _image_to_tool() -> "dict[str, str]":
    """{container image -> tool id} from the registry (built once)."""
    tools_dir = Path(__file__).resolve().parents[2] / "registry" / "tools"
    out: "dict[str, str]" = {}
    for p in tools_dir.rglob("*.yaml"):
        text = p.read_text(encoding="utf-8")
        gid = re.search(r"^id:\s*(\S+)", text, re.M)
        img = re.search(r"^\s*image:\s*(\S+)", text, re.M)
        if gid and img:
            out[img.group(1)] = gid.group(1)
    return out


def refs_root() -> "Path | None":
    """The references root DB management writes to, from ``$BIOFLOW_REFS``.

    Returns None when unset — DB auto-management is opt-in: without a refs
    location bioflow has nowhere to put databases, so the run-time hook is a
    no-op (and tests / offline runs are unaffected).
    """
    root = os.environ.get(REFS_ENV)
    return Path(root) if root else None


def ensure_dbs_for_image(image: str, dest_root: "Path | None" = None, *,
                         auto_update: bool = True, _fetch=None) -> "list[dict]":
    """Version-gate the DBs of whatever tool *image* is, just before it runs.

    Called by the stage runner.  Resolves the refs root from ``$BIOFLOW_REFS``
    (unless *dest_root* is given); if that is unset, or the image is not an
    annotation tool with versioned DBs, it is a no-op.  Best-effort: any DB
    error is logged, never raised, so it can never break a pipeline run.
    """
    if dest_root is None:
        dest_root = refs_root()
        if dest_root is None:
            return []
    tool_id = _image_to_tool().get(image)
    if not tool_id or not dbs_for_tool(tool_id):
        return []
    try:
        return ensure_db_current(tool_id, dest_root, auto_update=auto_update,
                                 _fetch=_fetch)
    except Exception as exc:                       # never break the run
        log.warning(f"DB ensure for {tool_id} skipped: {exc}")
        return []


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
