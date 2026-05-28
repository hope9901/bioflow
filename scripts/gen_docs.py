"""Generate the auto-reference doc pages from the registry + recipes.

Produces:
  docs/reference/tools.md    — every tool YAML grouped by category
  docs/reference/recipes.md  — every registered recipe + its DAG

Run before `mkdocs build` (the docs CI workflow does this).  Re-running
keeps the docs in sync with the registry without hand-editing.

    python scripts/gen_docs.py
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "registry" / "tools"
OUT_DIR = REPO_ROOT / "docs" / "reference"


def gen_tools() -> str:
    by_cat: dict[str, list[dict]] = {}
    for p in sorted(TOOLS_DIR.rglob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        by_cat.setdefault(d.get("category", "uncategorized"), []).append(d)

    total = sum(len(v) for v in by_cat.values())
    lines = [
        "# Tools",
        "",
        f"**{total} tools** across {len(by_cat)} categories, all pulled as "
        "BioContainer / public images on first use.  This page is "
        "auto-generated from `registry/tools/` by `scripts/gen_docs.py`.",
        "",
    ]
    for cat in sorted(by_cat):
        tools = sorted(by_cat[cat], key=lambda d: d["id"])
        lines.append(f"## {cat}  ({len(tools)})")
        lines.append("")
        lines.append("| Tool | Version | Image | Citation |")
        lines.append("|---|---|---|---|")
        for d in tools:
            dep = " ⚠️ deprecated" if d.get("deprecated") else ""
            img = d.get("container", {}).get("image", "")
            cit = d.get("citation", "").replace("|", "/")
            lines.append(
                f"| `{d['id']}`{dep} | {d.get('version','')} | "
                f"`{img}` | {cit} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def gen_recipes() -> str:
    # Import after sys.path is set by running from repo root
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from bioflow.recipes import get, names  # noqa: PLC0415

    lines = [
        "# Recipes",
        "",
        f"**{len(names())} recipes**, each invokable as "
        "`bioflow recipe run <name> [options]`.  Auto-generated from the "
        "recipe registry by `scripts/gen_docs.py`.",
        "",
    ]
    for name in sorted(names()):
        pipe = get(name)
        lines.append(f"## `{name}`")
        lines.append("")
        lines.append(f"{pipe.description}")
        lines.append("")
        try:
            plan = pipe.dry_run()
            lines.append(f"*{plan['n_stages']} stage(s):*")
            lines.append("")
            for s in plan["stages"]:
                lines.append(f"- **{s['name']}** — `{s.get('image','')}`")
            lines.append("")
        except Exception:
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "tools.md").write_text(gen_tools(), encoding="utf-8")
    (OUT_DIR / "recipes.md").write_text(gen_recipes(), encoding="utf-8")
    print(f"Wrote {OUT_DIR / 'tools.md'}")
    print(f"Wrote {OUT_DIR / 'recipes.md'}")


if __name__ == "__main__":
    main()
