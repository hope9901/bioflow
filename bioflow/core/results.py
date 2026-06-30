"""Results harvesting + overview report — visualization Layers 1 & 2.

EXPERIMENTAL prototype (one recipe: ``prokaryote_assembly``).  Post-processes a
finished workspace into:

* **Layer 1 — tidy, analysis-ready data** the researcher plots themselves:
  ``results/assembly_metrics.csv`` (one row per sample) + ``results/results.json``
  (a manifest naming the tables + their column schema).
* **Layer 2 — an at-a-glance overview**: ``results/overview.html``, a
  self-contained page with a metrics table and a few canonical inline-SVG bar
  charts.  No server, no JS dependency — embeddable straight into the RO-Crate.

Design stance: bioflow hands over clean data + a canonical summary; it does NOT
try to be a bespoke figure GUI.  Deep/interactive views are delegated to
standard tools (emit BAM+BAI / BED / GFF and open them in IGV).
"""
from __future__ import annotations

import csv
import datetime as _dt
import html
import json
from pathlib import Path

from bioflow.core.logger import get_logger

log = get_logger()

# Columns of the tidy per-sample table, in display order.
_COLUMNS = [
    "sample_id", "n_contigs", "total_bp", "n50", "gc_pct",
    "largest_contig", "cds", "rrna", "trna", "reads_after",
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


# ---------------------------------------------------------------------------
# Harvest — workspace → tidy rows
# ---------------------------------------------------------------------------

def harvest_prokaryote_assembly(workspace: Path) -> "list[dict]":
    """One tidy row per sample, parsed from each sample's Prokka/QUAST/fastp.

    Works for a single ``recipe run`` (sample outputs directly under the
    workspace) and a ``cohort`` run (one ``<sample_id>/`` subdir each): the
    Prokka ``--prefix`` names the report ``<sample_id>.txt``, and the sample
    root is the dir holding that stage's ``.cache``.
    """
    rows: "list[dict]" = []
    for ptxt in sorted(workspace.rglob("prokka/*.txt")):
        sid = ptxt.stem
        root = ptxt.parents[3] if len(ptxt.parents) >= 4 else workspace
        row: dict = {"sample_id": sid}
        row.update(_parse_prokka(ptxt))
        quast = next(iter(root.rglob("report.tsv")), None)
        if quast is not None:
            row.update(_parse_quast(quast))     # QUAST wins for shared metrics
        fastp = next(iter(root.rglob("fastp.json")), None)
        if fastp is not None:
            row.update(_parse_fastp(fastp))
        rows.append(row)
    return rows


_HARVESTERS = {"prokaryote_assembly": harvest_prokaryote_assembly}


# ---------------------------------------------------------------------------
# Layer 1 — write tidy data + manifest
# ---------------------------------------------------------------------------

def write_results(recipe: str, rows: "list[dict]", out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "assembly_metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    manifest = {
        "recipe": recipe,
        "generated": _now(),
        "n_samples": len(rows),
        "tables": [{
            "name": csv_path.name,
            "rows": len(rows),
            "columns": _COLUMNS,
            "description": "Per-sample assembly + annotation metrics "
                           "(tidy, one row per sample — plot however you like).",
        }],
        "samples": rows,
    }
    manifest_path = out_dir / "results.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"csv": csv_path, "manifest": manifest_path}


# ---------------------------------------------------------------------------
# Layer 2 — canonical overview (self-contained inline-SVG HTML)
# ---------------------------------------------------------------------------

def _svg_bars(rows: "list[dict]", metric: str, label: str, color: str) -> str:
    pts: "list[tuple[str, int]]" = []
    for r in rows:
        v = r.get(metric)
        if isinstance(v, int):          # charted metrics (bp / N50 / CDS) are ints
            pts.append((str(r["sample_id"]), v))
    if not pts:
        return f"<p class='muted'>{html.escape(label)}: no data</p>"
    maxv = max(v for _, v in pts) or 1
    left, bw, bh, gap = 130, 360, 22, 12
    h = len(pts) * (bh + gap) + 24
    out = [f"<svg width='{left + bw + 90}' height='{h}' role='img' "
           f"aria-label='{html.escape(label)}'>",
           f"<text x='0' y='14' class='cap'>{html.escape(label)}</text>"]
    for i, (sid, v) in enumerate(pts):
        y = 24 + i * (bh + gap)
        w = int(bw * (v / maxv))
        out.append(f"<text x='0' y='{y + bh - 6}' class='lbl'>{html.escape(sid)}</text>")
        out.append(f"<rect x='{left}' y='{y}' width='{w}' height='{bh}' "
                   f"rx='3' fill='{color}'/>")
        out.append(f"<text x='{left + w + 6}' y='{y + bh - 6}' class='val'>"
                   f"{v:,}</text>")
    out.append("</svg>")
    return "\n".join(out)


def _table(rows: "list[dict]") -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in _COLUMNS)
    body = []
    for r in rows:
        cells = []
        for c in _COLUMNS:
            v = r.get(c, "")
            cells.append(f"<td>{html.escape(f'{v:,}' if isinstance(v, int) else str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_overview(recipe: str, rows: "list[dict]", out_html: Path) -> Path:
    charts = "\n".join([
        _svg_bars(rows, "total_bp", "Assembly size (bp)", "#2c7be5"),
        _svg_bars(rows, "n50", "Contiguity — N50 (bp)", "#00a36c"),
        _svg_bars(rows, "cds", "Annotated CDS", "#9b59b6"),
    ])
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>bioflow overview — {html.escape(recipe)}</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:920px;margin:2rem auto;color:#222;}}
 h1{{color:#2c7be5;margin-bottom:.2rem;}} .muted{{color:#888;}}
 table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem;font-size:.9rem;}}
 th,td{{border:1px solid #e3e3e3;padding:.35rem .55rem;text-align:right;}}
 th:first-child,td:first-child{{text-align:left;}} th{{background:#f4f6fa;}}
 tr:nth-child(even){{background:#fafafa;}}
 .cap{{font-weight:600;font-size:13px;fill:#333;}} .lbl{{font-size:12px;fill:#333;}}
 .val{{font-size:11px;fill:#555;}} svg{{margin:.4rem 0 1.1rem;}}
 .note{{font-size:.8rem;color:#666;border-left:3px solid #2c7be5;padding:.2rem .8rem;background:#f7f9fc;}}
</style></head><body>
<h1>{html.escape(recipe)} — overview</h1>
<p class="muted">{len(rows)} sample(s) · generated {_now()}</p>
<p class="note">This is the <b>at-a-glance</b> view. The same numbers are in
<code>assembly_metrics.csv</code> (tidy, one row/sample) + <code>results.json</code>
— load those to make your own figures.</p>
<h2>Metrics</h2>
{_table(rows)}
<h2>At a glance</h2>
{charts}
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
    if recipe not in _HARVESTERS:
        raise ValueError(
            f"No results harvester for recipe {recipe!r} yet "
            f"(have: {', '.join(sorted(_HARVESTERS))})."
        )
    rows = _HARVESTERS[recipe](workspace)
    if not rows:
        raise ValueError(f"No per-sample outputs found under {workspace}.")
    out_dir = Path(out_dir) if out_dir else workspace / "results"
    paths = write_results(recipe, rows, out_dir)
    paths["overview"] = render_overview(recipe, rows, out_dir / "overview.html")
    paths["rows"] = rows
    return paths
