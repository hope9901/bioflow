"""Unit tests for update/release_watch.py — version comparison, candidate
file generation, state tracking.  GitHub API calls are stubbed."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "update"))

import release_watch as rw

TOOL_TEMPLATE = """\
id: dummytool
name: DummyTool
version: "1.0.0"
category: qc
stage: [genome_assembly.step1]
applicable: {{species: [any], read_type: [any], mode: [any]}}
container: {{image: staphb/dummytool:1.0.0}}
resources:
  min: {{cpu: 1, ram_gb: 1}}
  recommended: {{cpu: 1, ram_gb: 1}}
command_template: "true"
added: "2026-01-01"
last_reviewed: "2026-01-01"
source_repo: {repo}
"""


class TestNormalizeTag:
    def test_strips_leading_v(self):
        assert rw._normalize_tag("v2.17.1") == "2.17.1"

    def test_strips_path_prefix(self):
        assert rw._normalize_tag("release/3.5.0") == "3.5.0"

    def test_strips_name_prefix(self):
        assert rw._normalize_tag("kraken2-2.1.6") == "2.1.6"

    def test_rolling_tags_are_none(self):
        for t in ("latest", "nightly", "continuous", "stable", "release"):
            assert rw._normalize_tag(t) is None

    def test_non_version_is_none(self):
        assert rw._normalize_tag("") is None
        assert rw._normalize_tag("main") is None

    def test_plain_version_passthrough(self):
        assert rw._normalize_tag("1.3.1") == "1.3.1"
        assert rw._normalize_tag("2026.02.0") == "2026.02.0"


class TestIsNewer:
    def test_yes(self):
        assert rw.is_newer("1.1.0", "1.0.9")
        assert rw.is_newer("2.0.0", "1.99.99")

    def test_no(self):
        assert not rw.is_newer("1.0.0", "1.0.0")
        assert not rw.is_newer("0.9.0", "1.0.0")


BIOCONTAINER_TEMPLATE = """\
id: gseapy
name: gseapy
version: "1.3.0"
category: enrichment
stage: [rnaseq_deg.step4]
applicable: {{species: [any], read_type: [any], mode: [any]}}
container:
  image: quay.io/biocontainers/gseapy:1.3.0--py311heb3b1e3_0
  image_digest: sha256:{old_digest}
resources:
  min: {{cpu: 1, ram_gb: 1}}
  recommended: {{cpu: 1, ram_gb: 1}}
command_template: "true"
added: "2026-01-01"
last_reviewed: "2026-01-01"
source_repo: zqfang/GSEApy
"""

_OLD = "0" * 64


def _fake_quay(tags):
    """An opener that returns *tags* (list of name strings, or (name, ts) pairs)
    as a quay tag-list response, with a synthetic manifest digest per tag."""
    def opener(url):
        out = []
        for i, t in enumerate(tags):
            name, ts = (t, i) if isinstance(t, str) else t
            out.append({
                "name": name,
                "start_ts": ts,
                "manifest_digest": "sha256:" + f"{i:064d}",
            })
        return {"tags": out}
    return opener


class TestMakeCandidate:

    def test_bumps_version_and_image(self):
        doc = yaml.safe_load(TOOL_TEMPLATE.format(repo="x/y"))
        cand = rw.make_candidate(doc, "1.1.0", "2026-05-15")
        assert cand["version"] == "1.1.0"
        assert cand["container"]["image"] == "staphb/dummytool:1.1.0"
        assert cand["last_reviewed"] == "2026-05-15"
        assert cand["update_meta"]["source"] == "release_watch"
        assert cand["update_meta"]["previous_version"] == "1.0.0"

    def test_never_carries_the_previous_digest(self):
        """A bumped tag must not inherit the old image's digest — that would
        pin the OLD image under a NEW version number."""
        doc = yaml.safe_load(BIOCONTAINER_TEMPLATE.format(old_digest=_OLD))
        # Real build for 1.3.1 exists in the same py311 family.
        cand = rw.make_candidate(
            doc, "1.3.1", "2026-07-30",
            opener=_fake_quay(["1.3.1--py311heb3b1e3_0", "1.3.1--py310haaa_0"]),
        )
        assert "image_digest" not in cand["container"]
        assert cand["update_meta"]["previous_digest"] == "sha256:" + _OLD
        assert any("pin_digests" in r for r in cand["update_meta"]["risks"])

    def test_resolves_real_biocontainer_tag_in_python_family(self):
        doc = yaml.safe_load(BIOCONTAINER_TEMPLATE.format(old_digest=_OLD))
        cand = rw.make_candidate(
            doc, "1.3.1", "2026-07-30",
            opener=_fake_quay([
                "1.3.1--py312he7d644a_0",
                "1.3.1--py311heb3b1e3_0",   # matches current family
                "1.3.1--py310h75e7593_0",
            ]),
        )
        # keeps the py311 family rather than jumping Python versions
        assert cand["container"]["image"] == (
            "quay.io/biocontainers/gseapy:1.3.1--py311heb3b1e3_0"
        )
        assert "unverified image tag" not in cand["update_meta"]["risks"]

    def test_flags_unverified_when_no_build_exists(self):
        doc = yaml.safe_load(BIOCONTAINER_TEMPLATE.format(old_digest=_OLD))
        cand = rw.make_candidate(
            doc, "9.9.9", "2026-07-30", opener=_fake_quay([]),
        )
        # falls back to a bare-version guess and says so
        assert cand["container"]["image"] == "quay.io/biocontainers/gseapy:9.9.9"
        assert "unverified image tag" in cand["update_meta"]["risks"]
        assert "image_digest" not in cand["container"]

    def test_self_built_image_flags_build_and_push(self):
        doc = yaml.safe_load(TOOL_TEMPLATE.format(repo="scverse/scanpy"))
        doc["container"]["image"] = "ghcr.io/hope9901/bioflow-scanpy:1.12.2"
        cand = rw.make_candidate(doc, "1.12.3", "2026-07-30")
        assert cand["container"]["image"] == (
            "ghcr.io/hope9901/bioflow-scanpy:1.12.3"
        )
        assert "image must be built and pushed" in cand["update_meta"]["risks"]


class TestPrune:

    def _reg(self, tmp_path: Path, tool: str, version: str) -> Path:
        reg = tmp_path / "registry" / "tools" / "qc"
        reg.mkdir(parents=True, exist_ok=True)
        (reg / f"{tool}.yaml").write_text(
            f"id: {tool}\nname: {tool}\nversion: \"{version}\"\n"
            "category: qc\ncontainer: {image: x:1}\n",
            encoding="utf-8",
        )
        return tmp_path / "registry" / "tools"

    def _cand(self, tmp_path: Path, month: str, tool: str, version: str) -> Path:
        d = tmp_path / "candidates" / month
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{tool}.yaml"
        p.write_text(f"id: {tool}\nversion: \"{version}\"\n", encoding="utf-8")
        return p

    def test_prunes_applied_and_superseded(self, tmp_path):
        reg = self._reg(tmp_path, "bwa", "0.7.19")
        self._reg(tmp_path, "salmon", "2.3.4")
        applied = self._cand(tmp_path, "2026-06", "bwa", "0.7.19")     # ==
        superseded = self._cand(tmp_path, "2026-06", "salmon", "2.2.1")  # reg newer
        actions = rw.prune(tmp_path / "candidates", reg, dry_run=False)
        assert not applied.exists()
        assert not superseded.exists()
        results = {a["tool"]: a["result"] for a in actions}
        assert results["bwa"] == "pruned"
        assert results["salmon"] == "pruned"

    def test_keeps_pending(self, tmp_path):
        reg = self._reg(tmp_path, "spades", "4.2.0")
        pending = self._cand(tmp_path, "2026-06", "spades", "4.3.0")   # cand newer
        actions = rw.prune(tmp_path / "candidates", reg, dry_run=False)
        assert pending.exists()
        assert actions[0]["result"] == "pending"

    def test_keeps_orphan(self, tmp_path):
        reg = self._reg(tmp_path, "bwa", "0.7.19")   # no 'ghost' tool
        orphan = self._cand(tmp_path, "2026-06", "ghost", "1.0")
        actions = rw.prune(tmp_path / "candidates", reg, dry_run=False)
        assert orphan.exists()
        assert actions[0]["result"] == "orphan"

    def test_dry_run_deletes_nothing(self, tmp_path):
        reg = self._reg(tmp_path, "bwa", "0.7.19")
        applied = self._cand(tmp_path, "2026-06", "bwa", "0.7.19")
        actions = rw.prune(tmp_path / "candidates", reg, dry_run=True)
        assert applied.exists()
        assert actions[0]["result"] == "would_prune"

    def test_version_format_quirk_counts_as_applied(self, tmp_path):
        """A GitHub-tag form like '8-0-4' equals the registry's '8.0.4'."""
        reg = self._reg(tmp_path, "antismash", "8.0.4")
        cand = self._cand(tmp_path, "2026-06", "antismash", "8-0-4")
        actions = rw.prune(tmp_path / "candidates", reg, dry_run=False)
        assert not cand.exists()
        assert "applied" in actions[0]["detail"]

    def test_removes_empty_month_dir(self, tmp_path):
        reg = self._reg(tmp_path, "bwa", "0.7.19")
        self._cand(tmp_path, "2026-06", "bwa", "0.7.19")
        rw.prune(tmp_path / "candidates", reg, dry_run=False)
        assert not (tmp_path / "candidates" / "2026-06").exists()


class TestNoStaleCandidatesInRepo:
    """CI guard: applied/superseded candidates must not linger in the repo.
    The dry-run prune over the real dirs is the check — if it finds anything to
    prune, run `python -m update.release_watch --prune`."""

    def test_no_applied_candidate_lingers(self):
        repo = Path(__file__).resolve().parents[2]
        cands = repo / "update" / "candidates"
        reg = repo / "registry" / "tools"
        if not cands.exists():
            return
        stale = [
            a["detail"] for a in rw.prune(cands, reg, dry_run=True)
            if a["result"] == "would_prune"
        ]
        assert not stale, (
            "applied/superseded candidates left in update/candidates/ — run "
            "`python -m update.release_watch --prune`:\n  " + "\n  ".join(stale)
        )


class TestResolveBiocontainer:

    def test_exact_version_not_prefix(self):
        """like:1.3.1 also returns 1.3.10 — the resolver must reject it."""
        img = rw.resolve_biocontainer_image(
            "quay.io/biocontainers/gseapy:1.3.0--py311heb3b1e3_0", "1.3.1",
            opener=_fake_quay(["1.3.10--py311h_0", "1.3.1--py311h_0"]),
        )
        assert img == "quay.io/biocontainers/gseapy:1.3.1--py311h_0"

    def test_none_for_non_biocontainer(self):
        assert rw.resolve_biocontainer_image(
            "ghcr.io/hope9901/x:1.0", "1.1", opener=_fake_quay(["1.1--x_0"]),
        ) is None

    def test_none_on_network_error(self):
        def boom(url):
            raise OSError("no network")
        assert rw.resolve_biocontainer_image(
            "quay.io/biocontainers/gseapy:1.3.0--py311h_0", "1.3.1", opener=boom,
        ) is None


class TestScan:

    def _setup(self, tmp_path: Path) -> Path:
        reg = tmp_path / "registry" / "tools" / "qc"
        reg.mkdir(parents=True)
        (reg / "dummy.yaml").write_text(
            TOOL_TEMPLATE.format(repo="dummy/repo"), encoding="utf-8",
        )
        return reg

    def test_files_candidate_when_upstream_newer(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value="1.1.0"):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "filed" for a in actions)
        # Candidate YAML landed
        filed = list(cands.rglob("dummytool.yaml"))
        assert len(filed) == 1
        d = yaml.safe_load(filed[0].read_text(encoding="utf-8"))
        assert d["version"] == "1.1.0"
        # State recorded
        s = json.loads(state.read_text(encoding="utf-8"))
        assert s["dummytool"]["last_filed_version"] == "1.1.0"

    def test_up_to_date_when_upstream_equal(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value="1.0.0"):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "up_to_date" for a in actions)
        assert not list(cands.rglob("*.yaml"))

    def test_skips_already_filed(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        state.write_text(
            json.dumps({"dummytool": {"last_filed_version": "1.1.0"}}),
            encoding="utf-8",
        )
        with patch.object(rw, "latest_release_tag", return_value="1.1.0"):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "already_filed" for a in actions)
        assert not list(cands.rglob("*.yaml"))

    def test_dry_run_writes_nothing(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value="1.1.0"):
            actions = rw.scan(reg, cands, state, dry_run=True)
        assert any(a["result"] == "would_file" for a in actions)
        assert not state.exists()
        assert not list(cands.rglob("*.yaml")) if cands.exists() else True

    def test_handles_no_releases(self, tmp_path):
        reg = self._setup(tmp_path)
        cands = tmp_path / "candidates"
        state = tmp_path / "state.json"
        with patch.object(rw, "latest_release_tag", return_value=None):
            actions = rw.scan(reg, cands, state, dry_run=False)
        assert any(a["result"] == "no_releases" for a in actions)

    def test_skips_tools_without_source_repo(self, tmp_path):
        reg = tmp_path / "registry" / "tools" / "qc"
        reg.mkdir(parents=True)
        # No source_repo field
        (reg / "no_src.yaml").write_text(
            "id: x\nversion: '1.0.0'\ncategory: qc\nstage: [genome_assembly.step1]\n"
            "applicable: {species: [any], read_type: [any], mode: [any]}\n"
            "container: {image: x:1}\n"
            "resources: {min: {cpu: 1, ram_gb: 1}, recommended: {cpu: 1, ram_gb: 1}}\n"
            "command_template: 'true'\nname: x\n",
            encoding="utf-8",
        )
        actions = rw.scan(
            reg, tmp_path / "candidates", tmp_path / "state.json",
            dry_run=False,
        )
        assert actions == []   # nothing checked


class TestBumpImageTag:
    def test_simple(self):
        assert rw._bump_image_tag("foo:1.0", "1.1") == "foo:1.1"

    def test_path(self):
        assert rw._bump_image_tag("a/b/c:1.0", "1.1") == "a/b/c:1.1"

    def test_no_tag_is_passthrough(self):
        assert rw._bump_image_tag("alpine", "1.1") == "alpine"
