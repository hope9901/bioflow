"""Unit tests for bioflow.core.ncbi — all HTTP calls are mocked."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bioflow.core.ncbi import (
    AssemblyInfo,
    NcbiError,
    _api_key,
    _get_json,
    _LEVEL_API,
    download_genomes,
    download_proteins,
    list_genomes,
    list_proteins,
)


# ---------------------------------------------------------------------------
# Helpers — fake HTTP responses
# ---------------------------------------------------------------------------

def _json_response(data: dict) -> MagicMock:
    """Return a mock context-manager that yields the JSON-encoded data."""
    body = json.dumps(data).encode()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__  = MagicMock(return_value=False)
    cm.read      = MagicMock(return_value=body)
    cm.headers   = {}
    return cm


def _text_response(text: str) -> MagicMock:
    body = text.encode()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__  = MagicMock(return_value=False)
    cm.read      = MagicMock(side_effect=[body, b""])  # first call returns data, then EOF
    cm.headers   = {}
    return cm


def _zip_response(files: dict[str, bytes]) -> MagicMock:
    """Build an in-memory ZIP and wrap it in a mock response."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    zip_bytes = buf.getvalue()

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__  = MagicMock(return_value=False)
    # Return in 128 KB chunks like _stream_to_file expects
    chunks = [zip_bytes[i:i+131072] for i in range(0, len(zip_bytes), 131072)]
    chunks.append(b"")   # EOF sentinel
    cm.read      = MagicMock(side_effect=chunks)
    cm.headers   = {"Content-Length": str(len(zip_bytes))}
    return cm


# ---------------------------------------------------------------------------
# Fake NCBI Datasets API responses
# ---------------------------------------------------------------------------

_FAKE_REPORT_PAGE1 = {
    "reports": [
        {
            "accession": "GCF_000001405.40",
            "assembly_info": {
                "assembly_level": "Complete Genome",
                "submission_date": "2022-01-01",
                "refseq_category": "reference genome",
            },
            "organism": {
                "organism_name": "Dickeya dadantii",
                "infraspecific_names": {"strain": "3937"},
            },
            "assembly_stats": {
                "total_sequence_length": "4800000",
                "number_of_scaffolds": "1",
            },
        },
        {
            "accession": "GCF_000002425.26",
            "assembly_info": {
                "assembly_level": "Scaffold",
                "submission_date": "2021-06-15",
                "refseq_category": "",
            },
            "organism": {
                "organism_name": "Dickeya solani",
                "infraspecific_names": {"strain": ""},
            },
            "assembly_stats": {
                "total_sequence_length": "4500000",
                "number_of_scaffolds": "45",
            },
        },
    ],
    "total_count": 2,
}

_FAKE_ESEARCH = {
    "esearchresult": {
        "count": "1250",
        "retmax": "0",
        "retstart": "0",
        "idlist": ["123456", "789012"],
        "webenv": "WEBENV_XYZ",
        "querykey": "1",
    }
}

_FAKE_ESUMMARY = {
    "result": {
        "123456": {
            "title": "hypothetical protein [Dickeya dadantii]",
            "organism": "Dickeya dadantii",
            "slen": 342,
        },
        "789012": {
            "title": "pectate lyase [Dickeya solani]",
            "organism": "Dickeya solani",
            "slen": 389,
        },
    }
}


# ---------------------------------------------------------------------------
# Tests: list_genomes
# ---------------------------------------------------------------------------

class TestListGenomes:
    def test_parses_assembly_info(self, tmp_path):
        opener = MagicMock(return_value=_json_response(_FAKE_REPORT_PAGE1))
        result = list_genomes("dickeya", max_results=10, _opener=opener)

        assert len(result) == 2
        assert result[0].accession == "GCF_000001405.40"
        assert result[0].organism  == "Dickeya dadantii"
        assert result[0].strain    == "3937"
        assert result[0].assembly_level == "Complete Genome"
        assert result[0].total_sequence_length == 4_800_000
        assert result[0].scaffold_count == 1
        assert result[0].is_reference is True

    def test_non_reference_parsed_correctly(self, tmp_path):
        opener = MagicMock(return_value=_json_response(_FAKE_REPORT_PAGE1))
        result = list_genomes("dickeya", max_results=10, _opener=opener)
        assert result[1].is_reference is False

    def test_level_filter_passed_to_api(self, tmp_path):
        opener = MagicMock(return_value=_json_response({"reports": [], "total_count": 0}))
        list_genomes("dickeya", assembly_level="complete", max_results=5, _opener=opener)
        call_args = opener.call_args
        url = call_args[0][0].full_url  # urllib.request.Request.full_url
        assert "complete_genome" in url

    def test_invalid_level_raises(self):
        with pytest.raises(NcbiError, match="Unknown assembly_level"):
            list_genomes("dickeya", assembly_level="supercontig", max_results=5)

    def test_empty_response_returns_empty_list(self):
        opener = MagicMock(return_value=_json_response({"reports": [], "total_count": 0}))
        result = list_genomes("unknowntaxon999", max_results=10, _opener=opener)
        assert result == []

    def test_max_results_respected(self):
        opener = MagicMock(return_value=_json_response(_FAKE_REPORT_PAGE1))
        result = list_genomes("dickeya", max_results=1, _opener=opener)
        assert len(result) == 1

    def test_reference_only_param_passed(self):
        opener = MagicMock(return_value=_json_response({"reports": [], "total_count": 0}))
        list_genomes("dickeya", reference_only=True, max_results=5, _opener=opener)
        url = opener.call_args[0][0].full_url
        assert "reference_only" in url

    def test_pagination_fetches_next_page(self):
        """When next_page_token is present and max_results not yet reached, fetch again."""
        page1 = {
            "reports": [_FAKE_REPORT_PAGE1["reports"][0]],
            "next_page_token": "TOKEN_ABC",
        }
        page2 = {
            "reports": [_FAKE_REPORT_PAGE1["reports"][1]],
        }
        opener = MagicMock(side_effect=[
            _json_response(page1),
            _json_response(page2),
        ])
        result = list_genomes("dickeya", max_results=10, _opener=opener)
        assert len(result) == 2
        assert opener.call_count == 2

    def test_assembly_str_representation(self):
        a = AssemblyInfo(
            accession="GCF_001",
            organism="Test sp.",
            strain="A1",
            assembly_level="Complete Genome",
            total_sequence_length=5_000_000,
            scaffold_count=1,
            is_reference=True,
        )
        s = str(a)
        assert "GCF_001" in s
        assert "5.0 Mb" in s
        assert "[REF]" in s


# ---------------------------------------------------------------------------
# Tests: download_genomes
# ---------------------------------------------------------------------------

class TestDownloadGenomes:
    def _opener_sequence(self, report_data, zip_files):
        """Return an opener that serves the report JSON, then a ZIP."""
        report_resp = _json_response(report_data)
        zip_resp    = _zip_response(zip_files)
        return MagicMock(side_effect=[report_resp, zip_resp])

    def test_extracts_fasta_from_zip(self, tmp_path):
        fake_fasta = b">seq1\nATGCATGC\n"
        opener = self._opener_sequence(
            _FAKE_REPORT_PAGE1,
            {"ncbi_dataset/data/GCF_000001405.40/GCF_000001405.40_genomic.fna": fake_fasta},
        )
        paths = download_genomes(
            "dickeya", tmp_path,
            max_assemblies=5, progress=False, _opener=opener,
        )
        assert len(paths) == 1
        assert paths[0].name == "GCF_000001405.40_GCF_000001405.40_genomic.fna"
        assert paths[0].read_bytes() == fake_fasta

    def test_multiple_assemblies_multiple_files(self, tmp_path):
        opener = self._opener_sequence(
            _FAKE_REPORT_PAGE1,
            {
                "ncbi_dataset/data/GCF_000001405.40/genome.fna": b">a\nATGC\n",
                "ncbi_dataset/data/GCF_000002425.26/genome.fna": b">b\nGGCC\n",
            },
        )
        paths = download_genomes(
            "dickeya", tmp_path, progress=False, _opener=opener
        )
        assert len(paths) == 2

    def test_no_assemblies_raises(self, tmp_path):
        opener = MagicMock(return_value=_json_response({"reports": [], "total_count": 0}))
        with pytest.raises(NcbiError, match="No assemblies found"):
            download_genomes("unknowntaxon999", tmp_path, progress=False, _opener=opener)

    def test_zip_with_no_fasta_raises(self, tmp_path):
        opener = self._opener_sequence(
            _FAKE_REPORT_PAGE1,
            {"ncbi_dataset/data/GCF_000001405.40/readme.txt": b"nothing here"},
        )
        with pytest.raises(NcbiError, match="no files matching"):
            download_genomes("dickeya", tmp_path, progress=False, _opener=opener)

    def test_zip_deleted_after_extraction(self, tmp_path):
        opener = self._opener_sequence(
            _FAKE_REPORT_PAGE1,
            {"ncbi_dataset/data/GCF_000001405.40/genome.fna": b">s\nATGC\n"},
        )
        download_genomes("dickeya", tmp_path, progress=False, _opener=opener)
        zips = list(tmp_path.glob("_ncbi_*.zip"))
        assert zips == []

    def test_max_assemblies_limits_download(self, tmp_path):
        """Only accessions up to max_assemblies are included in the download URL."""
        opener = self._opener_sequence(
            _FAKE_REPORT_PAGE1,
            {"ncbi_dataset/data/GCF_000001405.40/genome.fna": b">s\nATGC\n"},
        )
        download_genomes("dickeya", tmp_path, max_assemblies=1, progress=False, _opener=opener)
        # Download call URL should only contain first accession
        dl_req = opener.call_args_list[1][0][0]   # second call = download
        assert "GCF_000001405.40" in dl_req.full_url
        # Second accession should NOT appear
        assert "GCF_000002425.26" not in dl_req.full_url

    def test_gff_included_when_requested(self, tmp_path):
        opener = self._opener_sequence(
            _FAKE_REPORT_PAGE1,
            {"ncbi_dataset/data/GCF_000001405.40/genes.gff": b"##gff-version 3\n"},
        )
        paths = download_genomes(
            "dickeya", tmp_path,
            include=("GENOME_GFF",), progress=False, _opener=opener,
        )
        assert paths[0].suffix == ".gff"


# ---------------------------------------------------------------------------
# Tests: list_proteins
# ---------------------------------------------------------------------------

class TestListProteins:
    def _esearch_then_esummary(self):
        return MagicMock(side_effect=[
            _json_response(_FAKE_ESEARCH),
            _json_response(_FAKE_ESUMMARY),
        ])

    def test_returns_total_and_records(self):
        opener = self._esearch_then_esummary()
        total, records = list_proteins("dickeya", _opener=opener)
        assert total == 1250
        assert len(records) == 2
        assert records[0]["uid"] == "123456"
        assert records[0]["organism"] == "Dickeya dadantii"
        assert records[0]["length"] == 342

    def test_empty_returns_zero_and_empty(self):
        empty_search = {
            "esearchresult": {"count": "0", "idlist": [], "webenv": "", "querykey": "1"}
        }
        opener = MagicMock(return_value=_json_response(empty_search))
        total, records = list_proteins("notreal999", _opener=opener)
        assert total == 0
        assert records == []

    def test_filter_term_included_in_query(self):
        opener = MagicMock(return_value=_json_response(
            {"esearchresult": {"count": "0", "idlist": [], "webenv": "", "querykey": "1"}}
        ))
        list_proteins("dickeya", filter_term="refseq[filter]", _opener=opener)
        url = opener.call_args[0][0].full_url
        assert "refseq" in url.lower() or "refseq" in urllib_decode(url).lower()

    def test_no_filter_term_omits_extra(self):
        opener = MagicMock(return_value=_json_response(
            {"esearchresult": {"count": "0", "idlist": [], "webenv": "", "querykey": "1"}}
        ))
        list_proteins("dickeya", filter_term="", _opener=opener)
        url = opener.call_args[0][0].full_url
        # Only organism filter, no AND appended
        assert "refseq" not in url


def urllib_decode(url: str) -> str:
    from urllib.parse import unquote
    return unquote(url)


# ---------------------------------------------------------------------------
# Tests: download_proteins
# ---------------------------------------------------------------------------

class TestDownloadProteins:
    def _opener_for_proteins(self, total: int, fasta_text: str):
        """Serve esearch (with webenv) then efetch."""
        esearch_resp = _json_response({
            "esearchresult": {
                "count": str(total),
                "retmax": "0",
                "idlist": [],
                "webenv": "WEBENV_TEST",
                "querykey": "1",
            }
        })
        # efetch returns plain text FASTA
        fasta_cm = MagicMock()
        fasta_cm.__enter__ = MagicMock(return_value=fasta_cm)
        fasta_cm.__exit__  = MagicMock(return_value=False)
        fasta_cm.read      = MagicMock(side_effect=[fasta_text.encode(), b""])
        fasta_cm.headers   = {}

        return MagicMock(side_effect=[esearch_resp, fasta_cm])

    def test_writes_fasta_file(self, tmp_path):
        fasta = ">prot1 [Dickeya dadantii]\nMACK\n>prot2 [Dickeya solani]\nMTRW\n"
        opener = self._opener_for_proteins(2, fasta)
        result = download_proteins(
            "dickeya", tmp_path, max_results=2, progress=False, _opener=opener
        )
        assert result.exists()
        assert result.name == "dickeya_proteins.faa"
        assert result.read_text(encoding="utf-8") == fasta

    def test_output_filename_slug(self, tmp_path):
        opener = self._opener_for_proteins(1, ">p\nM\n")
        result = download_proteins(
            "Dickeya dadantii", tmp_path, max_results=1, progress=False, _opener=opener
        )
        assert result.name == "dickeya_dadantii_proteins.faa"

    def test_no_results_raises(self, tmp_path):
        empty_search = _json_response({
            "esearchresult": {
                "count": "0", "idlist": [], "webenv": "", "querykey": "1"
            }
        })
        opener = MagicMock(return_value=empty_search)
        with pytest.raises(NcbiError, match="No proteins found"):
            download_proteins("notreal999", tmp_path, progress=False, _opener=opener)

    def test_file_deleted_on_error(self, tmp_path):
        """Partial FASTA file must be cleaned up when efetch raises."""
        esearch_resp = _json_response({
            "esearchresult": {
                "count": "100", "retmax": "0", "idlist": [],
                "webenv": "WE", "querykey": "1",
            }
        })
        efetch_cm = MagicMock()
        efetch_cm.__enter__ = MagicMock(return_value=efetch_cm)
        efetch_cm.__exit__  = MagicMock(return_value=False)
        efetch_cm.read      = MagicMock(side_effect=OSError("network dead"))
        efetch_cm.headers   = {}

        opener = MagicMock(side_effect=[esearch_resp, efetch_cm])
        with pytest.raises(NcbiError):
            download_proteins("dickeya", tmp_path, max_results=50, progress=False, _opener=opener)

        leftover = list(tmp_path.glob("*.faa"))
        assert leftover == []

    def test_batching_when_max_exceeds_batch(self, tmp_path):
        """max_results > 500 → multiple efetch calls."""
        esearch_resp = _json_response({
            "esearchresult": {
                "count": "1200", "retmax": "0", "idlist": [],
                "webenv": "WE", "querykey": "1",
            }
        })

        def _make_fasta_cm(text):
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=cm)
            cm.__exit__  = MagicMock(return_value=False)
            cm.read      = MagicMock(side_effect=[text.encode(), b""])
            cm.headers   = {}
            return cm

        opener = MagicMock(side_effect=[
            esearch_resp,
            _make_fasta_cm(">b1\nM\n"),   # batch 1 (500)
            _make_fasta_cm(">b2\nM\n"),   # batch 2 (500)
            _make_fasta_cm(">b3\nM\n"),   # batch 3 (200)
        ])
        result = download_proteins(
            "dickeya", tmp_path, max_results=1200, progress=False, _opener=opener
        )
        # 1 esearch + 3 efetch calls
        assert opener.call_count == 4
        assert result.exists()


# ---------------------------------------------------------------------------
# Tests: API key and _get_json
# ---------------------------------------------------------------------------

class TestApiKey:
    def test_api_key_read_from_env(self, monkeypatch):
        monkeypatch.setenv("NCBI_API_KEY", "TESTKEY123")
        assert _api_key() == "TESTKEY123"

    def test_api_key_absent_returns_none(self, monkeypatch):
        monkeypatch.delenv("NCBI_API_KEY", raising=False)
        assert _api_key() is None

    def test_get_json_raises_on_http_error(self):
        import urllib.error
        err = urllib.error.HTTPError(
            url="https://example.com", code=404, msg="Not Found",
            hdrs=None, fp=io.BytesIO(b"taxon not found"),
        )
        opener = MagicMock(side_effect=err)
        with pytest.raises(NcbiError, match="HTTP 404"):
            _get_json("https://api.ncbi.nlm.nih.gov/test", _opener=opener)

    def test_get_json_wraps_connection_error(self):
        opener = MagicMock(side_effect=OSError("Connection refused"))
        with pytest.raises(NcbiError, match="Request failed"):
            _get_json("https://api.ncbi.nlm.nih.gov/test", _opener=opener)
