"""Unit tests for bioflow.core.approve."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bioflow.core.approve import (
    ApprovalError,
    _append_changelog,
    approve_all_candidates,
    approve_candidate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_TOOL: dict = {
    "id": "hypo_assembler",
    "name": "Hypo Assembler",
    "version": "1.0.0",
    "category": "assembly",
    "stage": ["genome_assembly.step2"],
    "input_types": ["short_paired"],
    "output_types": ["assembly_fasta"],
    "applicable": {
        "species": ["prokaryote"],
        "read_type": ["short"],
        "mode": ["de_novo"],
    },
    "container": {
        "image": "example/hypo:1.0.0",
        "pull_policy": "if_not_present",
    },
    "resources": {
        "min": {"cpu": 4, "ram_gb": 8, "disk_gb": 20},
        "recommended": {"cpu": 16, "ram_gb": 32, "disk_gb": 100},
        "gpu": False,
        "arch": ["x86_64"],
    },
    "command_template": "hypo -1 {r1} -2 {r2} -o {out_dir}",
    "references": [],
    "citation": "Doe 2026",
    "added": "2026-04-17",
    "last_reviewed": "2026-04-17",
}

_UPDATE_META: dict = {
    "month": "2026-04",
    "replaces": ["old_assembler"],
    "benchmark_note": "30 % faster on E. coli",
    "risks": ["experimental"],
}


def _write_candidate(tmp_path: Path, extra_meta: bool = True) -> Path:
    data = dict(_VALID_TOOL)
    if extra_meta:
        data["update_meta"] = _UPDATE_META
    p = tmp_path / "hypo_assembler.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def _make_registry(tmp_path: Path) -> Path:
    """Create a minimal registry with a permissive schema."""
    reg = tmp_path / "registry"
    (reg / "tools" / "assembly").mkdir(parents=True, exist_ok=True)
    # Permissive schema: just require 'id' and 'category'
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["id", "category"],
        "properties": {
            "id":       {"type": "string"},
            "category": {"type": "string"},
        },
        "additionalProperties": True,
    }
    (reg / "schema.yaml").write_text(yaml.dump(schema), encoding="utf-8")
    return reg


# ---------------------------------------------------------------------------
# Tests: approve_candidate
# ---------------------------------------------------------------------------

class TestApproveCandidate:
    def test_approve_writes_clean_yaml(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = _make_registry(tmp_path)

        dest = approve_candidate(candidate, registry_dir=reg)

        assert dest.exists()
        written = yaml.safe_load(dest.read_text(encoding="utf-8"))
        # update_meta must be stripped
        assert "update_meta" not in written
        assert written["id"] == "hypo_assembler"

    def test_approve_destination_path(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = _make_registry(tmp_path)

        dest = approve_candidate(candidate, registry_dir=reg)

        assert dest == reg / "tools" / "assembly" / "hypo_assembler.yaml"

    def test_approve_missing_candidate_raises(self, tmp_path):
        reg = _make_registry(tmp_path)
        with pytest.raises(ApprovalError, match="not found"):
            approve_candidate(tmp_path / "nonexistent.yaml", registry_dir=reg)

    def test_approve_missing_schema_raises(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = tmp_path / "empty_registry"
        reg.mkdir()
        (reg / "tools").mkdir()
        with pytest.raises(ApprovalError, match="schema not found"):
            approve_candidate(candidate, registry_dir=reg)

    def test_approve_conflict_raises_without_overwrite(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = _make_registry(tmp_path)

        # First approval
        approve_candidate(candidate, registry_dir=reg)
        # Re-write candidate (it wasn't deleted)
        candidate = _write_candidate(tmp_path)

        with pytest.raises(ApprovalError, match="already exists"):
            approve_candidate(candidate, registry_dir=reg)

    def test_approve_overwrite_replaces(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = _make_registry(tmp_path)

        dest = approve_candidate(candidate, registry_dir=reg)
        old_mtime = dest.stat().st_mtime

        candidate = _write_candidate(tmp_path)
        dest2 = approve_candidate(candidate, registry_dir=reg, overwrite=True)

        assert dest2 == dest
        assert dest2.stat().st_mtime >= old_mtime

    def test_approve_dry_run_does_not_write(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = _make_registry(tmp_path)

        dest = approve_candidate(candidate, registry_dir=reg, dry_run=True)

        # dest is returned but file not written
        assert not dest.exists()

    def test_approve_delete_candidate(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = _make_registry(tmp_path)

        approve_candidate(candidate, registry_dir=reg, delete_candidate=True)

        assert not candidate.exists()

    def test_approve_no_delete_by_default(self, tmp_path):
        candidate = _write_candidate(tmp_path)
        reg = _make_registry(tmp_path)

        approve_candidate(candidate, registry_dir=reg)

        assert candidate.exists()

    def test_approve_without_update_meta(self, tmp_path):
        """Candidate without update_meta should still work."""
        candidate = _write_candidate(tmp_path, extra_meta=False)
        reg = _make_registry(tmp_path)

        dest = approve_candidate(candidate, registry_dir=reg)
        assert dest.exists()


# ---------------------------------------------------------------------------
# Tests: approve_all_candidates
# ---------------------------------------------------------------------------

class TestApproveAllCandidates:
    def _two_candidates(self, tmp_path: Path):
        """Write two valid candidates with different ids."""
        c_dir = tmp_path / "candidates"
        c_dir.mkdir()

        for tool_id in ("tool_a", "tool_b"):
            data = dict(_VALID_TOOL, id=tool_id)
            data["update_meta"] = _UPDATE_META
            (c_dir / f"{tool_id}.yaml").write_text(yaml.dump(data))

        return c_dir

    def test_approve_all_returns_results(self, tmp_path):
        c_dir = self._two_candidates(tmp_path)
        reg = _make_registry(tmp_path)

        results = approve_all_candidates(c_dir, registry_dir=reg)

        assert len(results) == 2
        assert all(r["status"] == "approved" for r in results)

    def test_approve_all_empty_dir_returns_empty(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        reg = _make_registry(tmp_path)

        results = approve_all_candidates(empty, registry_dir=reg)
        assert results == []

    def test_approve_all_conflict_skipped(self, tmp_path):
        c_dir = self._two_candidates(tmp_path)
        reg = _make_registry(tmp_path)

        # First run
        approve_all_candidates(c_dir, registry_dir=reg)
        # Second run without overwrite
        results = approve_all_candidates(c_dir, registry_dir=reg)

        assert all(r["status"] == "skipped" for r in results)

    def test_approve_all_overwrite(self, tmp_path):
        c_dir = self._two_candidates(tmp_path)
        reg = _make_registry(tmp_path)

        approve_all_candidates(c_dir, registry_dir=reg)
        results = approve_all_candidates(c_dir, registry_dir=reg, overwrite=True)

        assert all(r["status"] == "approved" for r in results)


# ---------------------------------------------------------------------------
# Tests: _append_changelog
# ---------------------------------------------------------------------------

class TestAppendChangelog:
    def test_changelog_created_if_missing(self, tmp_path, monkeypatch):
        import bioflow.core.approve as approve_mod
        monkeypatch.setattr(approve_mod, "CHANGELOG_PATH", tmp_path / "CHANGELOG.md")

        _append_changelog("my_tool", "assembly", _UPDATE_META, Path("my_tool.yaml"))

        cl = tmp_path / "CHANGELOG.md"
        assert cl.exists()
        text = cl.read_text(encoding="utf-8")
        assert "my_tool" in text
        assert "2026-04" in text

    def test_changelog_appended(self, tmp_path, monkeypatch):
        import bioflow.core.approve as approve_mod
        cl = tmp_path / "CHANGELOG.md"
        cl.write_text("# Registry changelog\n", encoding="utf-8")
        monkeypatch.setattr(approve_mod, "CHANGELOG_PATH", cl)

        _append_changelog("tool_x", "qc", {}, Path("tool_x.yaml"))
        _append_changelog("tool_y", "assembly", {}, Path("tool_y.yaml"))

        text = cl.read_text(encoding="utf-8")
        assert "tool_x" in text
        assert "tool_y" in text

    def test_changelog_includes_replaces_and_risks(self, tmp_path, monkeypatch):
        import bioflow.core.approve as approve_mod
        monkeypatch.setattr(approve_mod, "CHANGELOG_PATH", tmp_path / "CHANGELOG.md")

        meta = {"replaces": ["old_qc"], "risks": ["may_crash"], "benchmark_note": "2x faster"}
        _append_changelog("new_qc", "qc", meta, Path("new_qc.yaml"))

        text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "old_qc" in text
        assert "may_crash" in text
        assert "2x faster" in text
