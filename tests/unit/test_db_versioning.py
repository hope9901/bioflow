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

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_annotation_dbs_are_versioned():
    for key in ("eggnog", "dbcan", "kofam", "antismash_db", "gtdbtk_r232", "pfam"):
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


def test_ensure_db_current_auto_updates_stale_by_default(tmp_path: Path):
    # dbCAN is provision-only (no download URL) so an auto-update just re-stamps.
    db.write_db_version("dbcan", tmp_path, "11")            # older than upstream
    sts = db.ensure_db_current("dbcan", tmp_path,           # default auto_update=True
                               _fetch=lambda u: "dbCAN-HMMdb-V13")
    st = next(s for s in sts if s["db"] == "dbcan")
    assert st["update_available"] is True
    assert db.installed_db_version("dbcan", tmp_path) == "13"   # refreshed in place


def test_ensure_db_current_no_update_only_flags(tmp_path: Path):
    db.write_db_version("dbcan", tmp_path, "11")
    sts = db.ensure_db_current("dbcan", tmp_path, auto_update=False,
                               _fetch=lambda u: "dbCAN-HMMdb-V13")
    st = next(s for s in sts if s["db"] == "dbcan")
    assert st["update_available"] is True
    assert db.installed_db_version("dbcan", tmp_path) == "11"   # left untouched


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


def test_new_annotation_tools_have_versioned_dbs():
    # DRAM + funannotate ship their own DBs; pfam_scan reuses the Pfam DB.
    assert db.catalog_version("dram") and db.catalog_version("funannotate_db")
    assert "pfam" in db.dbs_for_tool("pfam_scan")
    assert "dram" in db.dbs_for_tool("dram")


def test_db_dependent_tools_all_have_a_catalog_entry():
    """Every tool that pins a /refs/dbs/<x> path must have a managed DB entry,
    so `bioflow db provision <tool's DB>` and the run-time hook actually work."""
    import yaml
    covered = set()
    for e in db._DB_CATALOG.values():
        covered |= set(e.get("used_by", []))
    gaps = []
    for p in (REPO_ROOT / "registry" / "tools").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        if d and d.get("references") and d["id"] not in covered:
            gaps.append(d["id"])
    assert not gaps, f"tools reference a DB path but have no _DB_CATALOG entry: {gaps}"


def test_latest_probe_injected_fetch_bypasses_cache():
    db._LATEST_CACHE.clear()
    assert db.latest_db_version("vep_cache", _fetch=lambda u: "release-120") == "120"
    assert "vep_cache" not in db._LATEST_CACHE  # test path is never cached


def _image_of(tool_id: str) -> str:
    return next(i for i, t in db._image_to_tool().items() if t == tool_id)


def test_run_hook_noop_without_refs(monkeypatch):
    """The stage-run hook does nothing unless $BIOFLOW_REFS points somewhere —
    so ordinary runs (and tests) never touch the network or download a DB."""
    monkeypatch.delenv("BIOFLOW_REFS", raising=False)
    assert db.ensure_dbs_for_image(_image_of("eggnog_mapper")) == []


def test_run_hook_uses_refs_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOFLOW_REFS", str(tmp_path))
    db.write_db_version("eggnog", tmp_path, "5.0.1")            # stale on disk
    sts = db.ensure_dbs_for_image(_image_of("eggnog_mapper"),
                                  auto_update=False, _fetch=lambda u: "")
    assert any(s["db"] == "eggnog" and s["update_available"] for s in sts)


def test_run_hook_noop_for_non_annotation_image(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOFLOW_REFS", str(tmp_path))
    assert db.ensure_dbs_for_image(_image_of("spades")) == []
