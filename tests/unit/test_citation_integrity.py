"""Guard: registry citation PMIDs must reference the cited work.

``scripts/fetch_tool_citations.py`` records, per tool, whether the PMID's paper
actually matches the citation's author + year (``verified``).  A batch of
registry PMIDs was once found to point at unrelated papers (a Netrin-1 study,
a career essay, a dental-implant paper …); these tests keep that from silently
coming back.

They run **offline** against the committed ``registry/tool_citations.json`` —
no network — so every CI run enforces them.  When you add or edit a tool's
``citation``, run ``python scripts/fetch_tool_citations.py`` to refresh the JSON
(that step does the online verification); a wrong PMID shows up as unverified
and fails the first test here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CITES = ROOT / "registry" / "tool_citations.json"
TOOLS = ROOT / "registry" / "tools"

# Tools whose canonical reference has no MEDLINE PMID (PeerJ CS, IEEE, a
# 'meta'omics environment paper, …), so their citation count is legitimately
# n/a.  Keep this list TIGHT: anything else unverified means a PMID points at
# the wrong paper and should be corrected, not allow-listed.
# Tools with no MEDLINE PMID: funannotate (Zenodo), GECCO (bioRxiv), sourmash
# (JOSS), seqtk (no paper) — their entries carry a DOI (or none) + verified=False.
KNOWN_UNVERIFIED = {"bracken", "bwa_mem2", "cafe5", "fragpipe", "kneaddata",
                    "funannotate", "gecco", "sourmash", "seqtk"}


def _load() -> dict:
    if not CITES.exists():
        pytest.skip("tool_citations.json not present")
    return json.loads(CITES.read_text(encoding="utf-8"))


def test_no_unexpected_unverified_citation():
    tools = _load()["tools"]
    unverified = {tid for tid, c in tools.items() if c.get("verified") is False}
    unexpected = unverified - KNOWN_UNVERIFIED
    assert not unexpected, (
        "these tools' citation PMID points at a paper whose author/year does "
        "not match the citation — fix the PMID in registry/tools (or add to "
        f"KNOWN_UNVERIFIED if genuinely not in MEDLINE): {sorted(unexpected)}"
    )


def test_allowlist_has_no_stale_entries():
    tools = _load()["tools"]
    unverified = {tid for tid, c in tools.items() if c.get("verified") is False}
    stale = KNOWN_UNVERIFIED - unverified - (set(KNOWN_UNVERIFIED) - set(tools))
    assert not stale, (
        f"KNOWN_UNVERIFIED lists tools that now verify — drop them: {sorted(stale)}"
    )


def test_every_registry_pmid_is_tracked():
    """A tool that cites a PMID must appear in tool_citations.json, so its
    reference is actually covered by the verification above.  A new tool with
    an untracked PMID is a gap — run the fetch script to include it."""
    tracked = set(_load()["tools"])
    missing = []
    for p in sorted(TOOLS.rglob("*.yaml")):
        text = p.read_text(encoding="utf-8")
        tid = re.search(r"^id:\s*(\S+)", text, re.M)
        has_pmid = re.search(r"^citation:.*PMID", text, re.M)
        if tid and has_pmid and tid.group(1) not in tracked:
            missing.append(tid.group(1))
    assert not missing, (
        "these tools cite a PMID but are absent from tool_citations.json — run "
        f"python scripts/fetch_tool_citations.py: {sorted(missing)}"
    )
