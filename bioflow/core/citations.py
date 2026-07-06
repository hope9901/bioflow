"""Resolve the citations (with DOIs) for the tools a recipe — or an explicit
list of tools — uses.

bioflow is plumbing; the science comes from the underlying tools, so users
should cite *those* in their methods.  This maps a recipe's stages (by image)
or explicit tool ids to each tool's registry citation + DOI, ready to paste
into a manuscript.  DOIs come from ``registry/tool_citations.json`` (fetched +
author/year-verified by ``scripts/fetch_tool_citations.py``); tools with no
MEDLINE record simply have no DOI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _ROOT / "registry" / "tools"
_CITES_JSON = _ROOT / "registry" / "tool_citations.json"


def _registry_tools() -> "dict[str, dict]":
    """``id -> {id, name, version, image, citation}`` from the tool YAMLs."""
    tools: "dict[str, dict]" = {}
    for p in sorted(_TOOLS_DIR.rglob("*.yaml")):
        t = p.read_text(encoding="utf-8")
        gid = re.search(r"^id:\s*(\S+)", t, re.M)
        if not gid:
            continue
        name = re.search(r"^name:\s*(.+)", t, re.M)
        ver = re.search(r'^version:\s*"?([^"\n]+?)"?\s*$', t, re.M)
        img = re.search(r"^\s*image:\s*(\S+)", t, re.M)
        cit = re.search(r'^citation:\s*"?(.*?)"?\s*$', t, re.M)
        tools[gid.group(1)] = {
            "id": gid.group(1),
            "name": name.group(1).strip().strip("\"'") if name else gid.group(1),
            "version": ver.group(1).strip() if ver else "",
            "image": img.group(1).strip() if img else "",
            "citation": cit.group(1).strip() if cit else "",
        }
    return tools


def _dois() -> "dict[str, str | None]":
    if not _CITES_JSON.exists():
        return {}
    data = json.loads(_CITES_JSON.read_text(encoding="utf-8"))
    return {tid: c.get("doi") for tid, c in data.get("tools", {}).items()}


def _entry(tool: dict, doi: "str | None") -> dict:
    return {
        "id": tool["id"], "name": tool["name"], "version": tool["version"],
        "citation": tool["citation"], "doi": doi,
    }


def citations_for_tools(ids: "list[str]") -> "tuple[list[dict], list[str]]":
    """(entries, unknown_ids) for the given tool ids, in the order requested."""
    reg = _registry_tools()
    dois = _dois()
    entries, unknown = [], []
    for tid in ids:
        if tid in reg:
            entries.append(_entry(reg[tid], dois.get(tid)))
        else:
            unknown.append(tid)
    return entries, unknown


def citations_for_recipe(name: str) -> "list[dict]":
    """Citations for every distinct tool a recipe's stages run (dedup, in
    stage order).  Raises ``KeyError`` if the recipe is unknown."""
    from bioflow.recipes import get  # noqa: PLC0415

    pipe = get(name)
    reg = _registry_tools()
    dois = _dois()
    by_image = {t["image"]: t for t in reg.values() if t["image"]}
    seen: "set[str]" = set()
    entries: "list[dict]" = []
    for stage in getattr(pipe, "stages", ()):
        tool = by_image.get(getattr(stage, "image", None))
        if tool and tool["id"] not in seen:
            seen.add(tool["id"])
            entries.append(_entry(tool, dois.get(tool["id"])))
    return entries


def _author_year(citation: str) -> "tuple[str, str]":
    m = re.match(r"\s*([A-Za-z\-]+).*?((?:19|20)\d{2})", citation)
    return (m.group(1), m.group(2)) if m else ("", "")


def format_text(entries: "list[dict]") -> str:
    lines = []
    for e in entries:
        ver = f" v{e['version']}" if e["version"] else ""
        ref = re.sub(r",?\s*PMID\s*\d+", "", e["citation"]).strip() or e["name"]
        doi = f"  https://doi.org/{e['doi']}" if e.get("doi") else "  (no DOI on record)"
        lines.append(f"- {e['name']}{ver} — {ref}.{doi}")
    return "\n".join(lines)


def format_bibtex(entries: "list[dict]") -> str:
    blocks = []
    for e in entries:
        key = re.sub(r"[^A-Za-z0-9]", "", e["id"]) or "tool"
        author, year = _author_year(e["citation"])
        fields = [f"  title = {{{e['name']} {e['version']}}}".rstrip()]
        if author:
            fields.append(f"  author = {{{author}}}")
        if year:
            fields.append(f"  year = {{{year}}}")
        if e.get("doi"):
            fields.append(f"  doi = {{{e['doi']}}}")
        fields.append(f"  note = {{{e['citation']}}}")
        blocks.append(f"@software{{{key},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(blocks)
