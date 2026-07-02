"""Results harvesting + overview report — visualization Layers 1 & 2.

EXPERIMENTAL.  Post-processes a finished workspace (single ``recipe run`` or a
``cohort``) into:

* **Layer 1 — tidy, analysis-ready data** the researcher plots themselves: a
  per-recipe ``results/<name>.csv`` (one row per sample) + ``results/results.json``
  (a manifest naming the tables + their column schema, and indexing each tool's
  report).
* **Layer 2 — an at-a-glance overview**: ``results/overview.html``, a
  self-contained page — a metrics table plus links to (or embeds of) each
  tool's *own* report.  No server, no JS dependency.

Design stance: bioflow hands over clean data + links to the field-standard viz
tools' output; it does NOT redraw plots or own a figure GUI.  Deep/interactive
views are delegated to standard tools (BAM+BAI / BED / GFF → IGV).

Recipes with a harvester so far: ``prokaryote_assembly`` (QUAST + Prokka +
fastp + Bandage) and ``metagenomics_profile`` (Bracken + Krona).  Add one by
registering it in :data:`_RECIPES`.
"""
from __future__ import annotations

import csv
import datetime as _dt
import html
import json
import os
from pathlib import Path

from bioflow.core.logger import get_logger

log = get_logger()

# Tidy per-sample table columns (display order), per recipe.
_ASM_COLUMNS = [
    "sample_id", "n_contigs", "total_bp", "n50", "gc_pct",
    "largest_contig", "cds", "rrna", "trna", "reads_after",
]
_META_COLUMNS = [
    "sample_id", "classified_reads", "n_taxa", "top_taxon", "top_fraction",
]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Per-tool parsers (best-effort — parse whatever is present)
# ---------------------------------------------------------------------------

def _parse_quast(path: Path) -> dict:
    want = {
        "# contigs": "n_contigs", "Total length": "total_bp", "N50": "n50",
        "GC (%)": "gc_pct", "Largest contig": "largest_contig",
    }
    out: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        k = k.strip()
        if k in want:                       # exact match excludes "(>= N bp)" rows
            out[want[k]] = float(v) if k == "GC (%)" else int(float(v))
    return out


def _parse_prokka(path: Path) -> dict:
    want = {"contigs": "n_contigs", "bases": "total_bp",
            "CDS": "cds", "rRNA": "rrna", "tRNA": "trna"}
    out: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        k, v = (s.strip() for s in line.split(":", 1))
        if k in want and v.isdigit():
            out[want[k]] = int(v)
    return out


def _parse_fastp(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return {"reads_after": d.get("summary", {})
                .get("after_filtering", {}).get("total_reads")}
    except Exception:
        return {}


def _parse_bracken(path: Path) -> dict:
    """Summarise a Bracken TSV (name / … / new_est_reads / fraction) into a
    per-sample row: total classified reads, taxa count, and the top taxon."""
    taxa: "list[tuple[str, int, float]]" = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        try:
            taxa.append((parts[0], int(parts[5]), float(parts[6])))
        except ValueError:
            continue
    if not taxa:
        return {}
    top = max(taxa, key=lambda t: t[1])
    return {
        "classified_reads": sum(t[1] for t in taxa),
        "n_taxa": len(taxa),
        "top_taxon": top[0],
        "top_fraction": round(top[2], 4),
    }


# ---------------------------------------------------------------------------
# Harvest — workspace → tidy rows
# ---------------------------------------------------------------------------

def _find_report(root: Path, pattern: str) -> "Path | None":
    """First match of *pattern* under *root*, skipping the staged _cohort_qc
    mirror tree (those are copies for MultiQC, not the originals)."""
    return next((p for p in root.rglob(pattern) if "_cohort_qc" not in p.parts), None)


def harvest_prokaryote_assembly(workspace: Path) -> "tuple[list[dict], dict]":
    """Per sample: a tidy metrics row + links to the tools' own report pages.

    Works for a single ``recipe run`` (outputs directly under the workspace)
    and a ``cohort`` run (one ``<sample_id>/`` subdir each): the Prokka
    ``--prefix`` names the report ``<sample_id>.txt`` and the sample root is the
    dir holding that stage's ``.cache``.
    """
    rows: "list[dict]" = []
    reports: "dict[str, dict[str, Path]]" = {}
    for ptxt in sorted(workspace.rglob("prokka/*.txt")):
        sid = ptxt.stem
        root = ptxt.parents[3] if len(ptxt.parents) >= 4 else workspace
        row: dict = {"sample_id": sid}
        row.update(_parse_prokka(ptxt))
        quast = _find_report(root, "report.tsv")
        if quast is not None:
            row.update(_parse_quast(quast))     # QUAST wins for shared metrics
        fastp = _find_report(root, "fastp.json")
        if fastp is not None:
            row.update(_parse_fastp(fastp))
        rows.append(row)
        # Links to the established tools' own report pages — paper-grade,
        # interactive; we surface them rather than redrawing the plots.
        found = {
            "Circular genome map (GenoVi)": _find_report(root, "genome_plot.png"),
            "QUAST report": _find_report(root, "report.html"),
            "Icarus contig browser": _find_report(root, "icarus.html"),
            "fastp read QC": _find_report(root, "fastp.html"),
            "Assembly graph (Bandage)": _find_report(root, "assembly_graph.png"),
        }
        reports[sid] = {k: v for k, v in found.items() if v is not None}
    return rows, reports


def harvest_metagenomics_profile(workspace: Path) -> "tuple[list[dict], dict]":
    """Per sample: a Bracken profile summary + a link to the Krona sunburst.

    The Bracken stage writes ``<sample_id>.bracken.tsv``; the sample root is the
    dir holding that stage's ``.cache``.
    """
    rows: "list[dict]" = []
    reports: "dict[str, dict[str, Path]]" = {}
    for bt in sorted(workspace.rglob("*.bracken.tsv")):
        if "_cohort_qc" in bt.parts:
            continue
        sid = bt.name[: -len(".bracken.tsv")]
        root = bt.parents[2] if len(bt.parents) >= 3 else workspace
        row: dict = {"sample_id": sid}
        row.update(_parse_bracken(bt))
        rows.append(row)
        found = {
            "Krona taxonomy (interactive)": _find_report(root, "krona.html"),
            "fastp read QC": _find_report(root, "fastp.html"),
        }
        reports[sid] = {k: v for k, v in found.items() if v is not None}
    return rows, reports


# recipe → how to harvest it + what its tidy table looks like.
_RECIPES: "dict[str, dict]" = {
    "prokaryote_assembly": {
        "harvest": harvest_prokaryote_assembly,
        "table": "assembly_metrics.csv",
        "columns": _ASM_COLUMNS,
        "desc": "Per-sample assembly + annotation metrics "
                "(tidy, one row per sample — plot however you like).",
    },
    "metagenomics_profile": {
        "harvest": harvest_metagenomics_profile,
        "table": "taxonomic_profile.csv",
        "columns": _META_COLUMNS,
        "desc": "Per-sample taxonomic profile summary from Bracken "
                "(tidy, one row per sample).",
    },
}


# ---------------------------------------------------------------------------
# Layer 1 — write tidy data + manifest
# ---------------------------------------------------------------------------

def write_results(recipe: str, rows: "list[dict]", reports: dict, out_dir: Path) -> dict:
    cfg = _RECIPES[recipe]
    columns = cfg["columns"]
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / cfg["table"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    manifest = {
        "recipe": recipe,
        "generated": _now(),
        "n_samples": len(rows),
        "tables": [{
            "name": csv_path.name,
            "rows": len(rows),
            "columns": columns,
            "description": cfg["desc"],
        }],
        # Each tool's own report page, relative to this manifest — the
        # canonical interactive views, not redrawn by bioflow.
        "reports": {
            sid: {label: _rel(p, out_dir) for label, p in links.items()}
            for sid, links in reports.items()
        },
        "samples": rows,
    }
    manifest_path = out_dir / "results.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"csv": csv_path, "manifest": manifest_path}


# ---------------------------------------------------------------------------
# Layer 2 — canonical overview (self-contained inline-SVG HTML)
# ---------------------------------------------------------------------------

def _rel(p: Path, base: Path) -> str:
    """A link from *base* to *p*: a clean relative path when they share a drive
    (the default, ``out`` inside the workspace), else an absolute ``file://`` URI
    (Windows can't relativise across drives)."""
    try:
        return os.path.relpath(p, base).replace(os.sep, "/")
    except ValueError:
        return Path(p).resolve().as_uri()


_IMAGE_SUFFIXES = {".png", ".svg", ".jpg", ".jpeg", ".gif"}


def _report_block(sid: str, links: "dict[str, Path]", base: Path) -> str:
    """One sample's reports: image outputs are embedded, HTML pages are linked."""
    if not links:
        return (f"<div class='rep'><span class='sid'>{html.escape(sid)}</span> "
                "<span class='muted'>no report pages found</span></div>")
    anchors, figures = [], []
    for label, p in links.items():
        href = html.escape(_rel(p, base))
        if p.suffix.lower() in _IMAGE_SUFFIXES:
            figures.append(
                f'<figure><a href="{href}"><img src="{href}" '
                f'alt="{html.escape(label)}" loading="lazy"></a>'
                f"<figcaption>{html.escape(label)}</figcaption></figure>")
        else:
            anchors.append(f'<a href="{href}">{html.escape(label)}</a>')
    body = " · ".join(anchors)
    if figures:
        body += "<div class='imgs'>" + "".join(figures) + "</div>"
    return f"<div class='rep'><span class='sid'>{html.escape(sid)}</span> {body}</div>"


def _table(rows: "list[dict]", columns: "list[str]") -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = []
    for r in rows:
        cells = []
        for c in columns:
            v = r.get(c, "")
            cells.append(f"<td>{html.escape(f'{v:,}' if isinstance(v, int) else str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_overview(recipe: str, rows: "list[dict]", reports: dict,
                    out_html: Path) -> Path:
    cfg = _RECIPES[recipe]
    base = out_html.parent
    report_blocks = "\n".join(
        _report_block(r["sample_id"], reports.get(r["sample_id"], {}), base)
        for r in rows
    )
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>bioflow overview — {html.escape(recipe)}</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:920px;margin:2rem auto;color:#222;}}
 h1{{color:#2c7be5;margin-bottom:.2rem;}} h2{{font-size:1.05rem;margin-top:1.6rem;}}
 .muted{{color:#888;}}
 table{{border-collapse:collapse;width:100%;margin:.5rem 0 1rem;font-size:.9rem;}}
 th,td{{border:1px solid #e3e3e3;padding:.35rem .55rem;text-align:right;}}
 th:first-child,td:first-child{{text-align:left;}} th{{background:#f4f6fa;}}
 tr:nth-child(even){{background:#fafafa;}}
 .rep{{padding:.5rem 0;font-size:.9rem;border-top:1px solid #eee;}}
 .sid{{font-weight:600;margin-right:.6rem;}}
 .rep a{{color:#2c7be5;text-decoration:none;margin-right:.2rem;}}
 .imgs{{display:flex;gap:14px;flex-wrap:wrap;margin:.5rem 0 .2rem;}}
 .imgs figure{{margin:0;}}
 .imgs img{{max-width:340px;max-height:240px;border:1px solid #e3e3e3;border-radius:6px;}}
 .imgs figcaption{{font-size:.75rem;color:#888;margin-top:.15rem;}}
 .note{{font-size:.8rem;color:#666;border-left:3px solid #2c7be5;padding:.2rem .8rem;background:#f7f9fc;}}
</style></head><body>
<h1>{html.escape(recipe)} — overview</h1>
<p class="muted">{len(rows)} sample(s) · generated {_now()}</p>
<p class="note">Headline numbers below; the same data is in
<code>{html.escape(cfg["table"])}</code> + <code>results.json</code> — load those
to make your own figures. The links open each tool's own interactive report —
bioflow surfaces those rather than redrawing them.</p>
<h2>Metrics</h2>
{_table(rows, cfg["columns"])}
<h2>Reports</h2>
{report_blocks}
</body></html>"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(page, encoding="utf-8")
    return out_html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_overview(recipe: str, workspace: Path, out_dir: "Path | None" = None) -> dict:
    """Harvest *workspace* into tidy data + an overview report.

    Returns ``{"csv", "manifest", "overview", "rows"}``.  Raises ValueError for
    a recipe without a harvester (only ``prokaryote_assembly`` for now).
    """
    workspace = Path(workspace)
    if recipe not in _RECIPES:
        raise ValueError(
            f"No results harvester for recipe {recipe!r} yet "
            f"(have: {', '.join(sorted(_RECIPES))})."
        )
    rows, reports = _RECIPES[recipe]["harvest"](workspace)
    if not rows:
        raise ValueError(f"No per-sample outputs found under {workspace}.")
    out_dir = Path(out_dir) if out_dir else workspace / "results"
    paths = write_results(recipe, rows, reports, out_dir)
    paths["overview"] = render_overview(recipe, rows, reports,
                                        out_dir / "overview.html")
    paths["rows"] = rows
    return paths


def has_harvester(recipe: str) -> bool:
    """Whether *recipe* can produce a results overview."""
    return recipe in _RECIPES


def maybe_build_overview(recipe: str, workspace: Path) -> "dict | None":
    """Build the overview at the end of a run, best-effort — never raises.

    Returns the paths dict on success, or ``None`` if the recipe has no
    harvester yet or harvesting failed (a warning is logged).
    """
    if recipe not in _RECIPES:
        return None
    try:
        return build_overview(recipe, Path(workspace))
    except Exception as exc:        # results are a convenience, never fatal
        log.warning(f"Results overview skipped: {exc}")
        return None
