"""Registry sanity guards — catch obvious mis-categorisations early.

The Dickeya session caught two tools shelved under the wrong category:
  * bwa_mem2  was filed as `assembly`  (it's a read aligner)
  * trimgalore was filed as `alignment` (it's a read trimmer / QC)

These tests encode a small set of "if a tool name contains X, its category
must / must not be Y" rules so regressions get caught at import time
instead of after the README is published.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from bioflow.core.registry import load_registry


@pytest.fixture(scope="module")
def all_tools():
    return load_registry(Path(__file__).resolve().parents[2] / "registry")


# ---------------------------------------------------------------------------
# Naming-vs-category sanity
# ---------------------------------------------------------------------------

class TestCategoryMatchesName:

    # Tool-name substring → category it MUST be in (exact or in this set)
    MUST_BE = {
        "bwa":         {"alignment", "rnaseq_align"},
        "bowtie":      {"alignment"},
        "minimap":     {"alignment"},
        "hisat":       {"rnaseq_align"},
        "salmon":      {"rnaseq_align"},
        "kallisto":    {"rnaseq_align"},
        "star":        {"rnaseq_align", "single_cell"},  # star or starsolo
        "fastqc":      {"qc"},
        "fastp":       {"qc"},
        "trimgalore":  {"qc"},
        "trim_galore": {"qc"},
        "filtlong":    {"qc"},
        "nanoplot":    {"qc"},
        "spades":      {"assembly"},
        "hifiasm":     {"assembly"},
        "flye":        {"assembly"},
        "unicycler":   {"assembly"},
        "prokka":      {"struct_annot"},
        "bakta":       {"struct_annot"},
        "braker":      {"struct_annot"},
        "busco":       {"assembly_qc"},
        "checkm":      {"assembly_qc"},
        "merqury":     {"assembly_qc"},
        "quast":       {"assembly_qc"},
        "deseq":       {"deg"},
        "edger":       {"deg"},
        "limma":       {"deg"},
        "scoary":      {"comparative_genomics"},
        "roary":       {"comparative_genomics"},
        "iqtree":      {"comparative_genomics"},
        "fastani":     {"comparative_genomics"},
        "abricate":    {"comparative_genomics"},
        "cafe":        {"comparative_genomics"},
    }

    def test_tool_categories_match_their_kind(self, all_tools):
        bad: list = []
        for tool in all_tools:
            for needle, allowed in self.MUST_BE.items():
                if needle in tool.id.lower():
                    if tool.category not in allowed:
                        bad.append(
                            f"{tool.id}: category={tool.category!r}, "
                            f"expected one of {sorted(allowed)!r} "
                            f"(matched substring {needle!r})"
                        )
                    break
        assert not bad, "Mis-categorised tools:\n  " + "\n  ".join(bad)


# ---------------------------------------------------------------------------
# Output-type sanity — aligners shouldn't claim `assembly_fasta`
# ---------------------------------------------------------------------------

class TestOutputTypesPlausible:

    def test_aligners_dont_claim_assembly_output(self, all_tools):
        bad = []
        for tool in all_tools:
            if tool.category in ("alignment", "rnaseq_align"):
                if "assembly_fasta" in tool.output_types:
                    bad.append(
                        f"{tool.id} ({tool.category}) lists "
                        f"output_types=[..., 'assembly_fasta', ...] "
                        "— aligners produce BAM / consensus FASTA, not "
                        "true assemblies."
                    )
        assert not bad, "Mis-typed outputs:\n  " + "\n  ".join(bad)


# ---------------------------------------------------------------------------
# No duplicates with different category
# ---------------------------------------------------------------------------

class TestVersionMatchesImageTag:
    """The ``version`` label must match the tool actually shipped in the image.

    Catches the drift where the image is bumped but the label is left stale —
    comet was pinned to a 2026.01.1 image yet still labelled ``2024.02.0``, so
    provenance and `bioflow db` reported the wrong version.  Bundle / mulled
    images legitimately differ (their tag is the *bundle*'s version or a content
    hash, not the tool's) and are allowlisted with the reason.
    """

    #: tool id → why its version can't match the image tag
    BUNDLE_IMAGES = {
        "bwa_samtools": "mulled bwa+samtools combo — the tag is a content hash",
        "repeatmasker": "dfam/tetools bundle — tag is the tetools version, not RepeatMasker's",
        "repeatmodeler": "dfam/tetools bundle — tag is the tetools version, not RepeatModeler's",
    }

    @staticmethod
    def _digits(s: str) -> str:
        return re.sub(r"\D", "", s)

    def test_version_matches_image_tag(self, all_tools):
        bad = []
        for t in all_tools:
            if t.id in self.BUNDLE_IMAGES:
                continue
            image = t.container.image
            if ":" not in image:
                continue
            # tag before the BioContainers build suffix (`--pyXXX_0`)
            tag = image.rsplit(":", 1)[1].split("--", 1)[0]
            if not tag or tag == "latest":
                continue
            ver = t.version
            # exact / substring match, or the same digit-run (comet's compact
            # `2026011` == labelled `2026.01.1`)
            if ver == tag or ver in tag or tag in ver:
                continue
            if self._digits(ver) == self._digits(tag):
                continue
            bad.append(
                f"{t.id}: version={ver!r} but image tag={tag!r} ({image}) — "
                "bump the version label to match the image, or add the tool to "
                "BUNDLE_IMAGES if the tag is a bundle version / content hash."
            )
        assert not bad, "version/image drift:\n  " + "\n  ".join(bad)


class TestNoCrossCategoryDuplicates:

    def test_no_two_tools_share_an_id(self, all_tools):
        seen: dict = {}
        for t in all_tools:
            assert t.id not in seen, (
                f"Tool id {t.id!r} registered twice: "
                f"first under {seen[t.id]!r}, again under {t.category!r}"
            )
            seen[t.id] = t.category

    def test_no_hard_coded_dickeya_or_taxon_in_command(self, all_tools):
        """Prevent recurrence of the prokka_comparative bug where
        '--genus Dickeya' was baked into a generic registry entry."""
        bad = []
        for t in all_tools:
            cmd = (t.command_template or "").lower()
            for needle in ("dickeya", "pectobacterium", "escherichia"):
                if f"--genus {needle}" in cmd or f"genus={needle}" in cmd:
                    bad.append(
                        f"{t.id}: command_template hard-codes "
                        f"genus {needle!r} — registry entries must stay "
                        "generic; per-taxon flags belong in the recipe "
                        "calling the tool."
                    )
        assert not bad, "Taxon-locked tools:\n  " + "\n  ".join(bad)
