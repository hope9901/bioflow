"""Version-gated reference-DB management + DB-version in citations.

A functional-annotation DB (eggNOG, dbCAN, KOfam, …) moves on its own release
cadence, so bioflow tracks its version and only re-downloads when upstream is
newer than the copy on disk — never on every run.  These lock that behaviour
and the DB-version passthrough into `bioflow cite`.

See bioflow/core/db.py and bioflow/core/citations.py.
"""
from __future__ import annotations

from pathlib import Path

from bioflow.core import citations, db


def test_annotation_dbs_are_versioned():
    for key in ("eggnog", "dbcan", "kofam", "antismash_db", "gtdbtk_r220", "pfam"):
        assert db.catalog_version(key), f"{key} must carry a version"
        assert key in db._DB_CATALOG


def test_marker_roundtrip_and_update_gate(tmp_path: Path):
    # nothing installed yet
    st = db.db_status("eggnog", tmp_path)
    assert st["present"] is False and st["update_available"] is False
    # install an older copy → update available vs the catalog version
    db.write_db_version("eggnog", tmp_path, "5.0.1")
    assert db.installed_db_version("eggnog", tmp_path) == "5.0.1"
    st = db.db_status("eggnog", tmp_path)
    assert st["installed"] == "5.0.1" and st["update_available"] is True
    # install the current version → no update (routine run won't re-download)
    db.write_db_version("eggnog", tmp_path, "5.0.2")
    assert db.db_status("eggnog", tmp_path)["update_available"] is False


def test_latest_probe_picks_highest(monkeypatch):
    body = "emapperdb-5.0.2  emapperdb-5.0.10  emapperdb-4.5.1"
    assert db.latest_db_version("eggnog", _fetch=lambda u: body) == "5.0.10"
    # offline / probe failure is silent -> None (treated as "no update")
    def boom(_u):
        raise OSError("offline")
    assert db.latest_db_version("eggnog", _fetch=boom) is None


def test_update_db_is_noop_when_current(tmp_path: Path):
    db.write_db_version("dbcan", tmp_path, "12")   # == catalog version
    res = db.update_db("dbcan", tmp_path, _fetch=lambda u: "")
    assert res["updated"] is False


def test_provision_command_targets_refs_dir(tmp_path: Path):
    cmd = db.provision_command("eggnog", tmp_path)
    assert cmd and "download_eggnog_data.py" in cmd
    assert str((tmp_path / "eggnog").resolve()) in cmd
    # URL-only DBs (no provision) return None
    assert db.provision_command("dbsnp_grch38", tmp_path) is None


def test_ensure_db_current_flags_but_does_not_download(tmp_path: Path):
    db.write_db_version("eggnog", tmp_path, "5.0.1")
    sts = db.ensure_db_current("eggnog_mapper", tmp_path, check_latest=False)
    egg = next(s for s in sts if s["db"] == "eggnog")
    assert egg["update_available"] is True
    # the eggnog file was never fetched — ensure only *flags* by default
    assert not (tmp_path / "eggnog" / "eggnog.db.gz").exists()


def test_cite_includes_db_version():
    entries, _ = citations.citations_for_tools(["eggnog_mapper", "kofamscan"])
    egg = next(e for e in entries if e["id"] == "eggnog_mapper")
    assert any(d["key"] == "eggnog" and d["version"] == "5.0.2"
               for d in egg["databases"])
    text = citations.format_text(entries)
    assert "eggNOG v5.0.2" in text and "KOfam v2024-01-01" in text


def test_cite_no_db_for_non_annotation_tool():
    entries, _ = citations.citations_for_tools(["spades"])
    assert entries[0]["databases"] == []
    assert "databases:" not in citations.format_text(entries)
