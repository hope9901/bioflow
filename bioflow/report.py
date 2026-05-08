"""bioflow.report — accumulate analysis results into a single HTML page.

Phase 2E.  Solves the Dickeya-session pain where ``build_report.py`` had
to be hand-edited 11 times.  Now the recipe (or a user script) accumulates
sections via a stateful :class:`Report` and renders one ``summary.html``
on demand.

Minimal usage
-------------
::

    from bioflow.report import Report
    report = Report(title="Dickeya pangenome", out_dir=workspace)
    report.add_section(
        "Annotation",
        body="Re-annotated 13 RefSeq genomes with Prokka 1.14.6",
        results=annotate_results,
    )
    report.add_figure("ANI heatmap", fig=plt_fig)
    report.add_table("Pangenome buckets", table=df)
    report.write()       # → <workspace>/summary.html

Design points
-------------
* Pure stdlib HTML — no Jinja, no Tailwind, no external CSS.  The output
  is one self-contained file that opens in any browser.
* Every text input is ``html.escape``-ed before insertion, so a tool's
  stderr containing ``<script>`` cannot inject markup.
* Figures: pass a Matplotlib ``Figure`` object; we ``savefig`` it under
  ``out_dir/figures/`` and reference it by relative URL.
* Tables: pandas DataFrame → ``to_html``; size-capped to top 50 rows.
* Stage results: pass a list of :class:`StageResult` to get a small chip
  showing cached/fresh/failed counts and the directories.
"""
from __future__ import annotations

import datetime
import html
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from bioflow.core.logger import get_logger

log = get_logger()


@dataclass
class _Section:
    title: str
    html: str
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)


class Report:
    """Stateful HTML report builder.

    Sections accumulate in declaration order.  Call :meth:`write` once at
    the end of your script / pipeline to render the page.  Multiple
    ``write()`` calls overwrite the previous file, so an in-progress
    pipeline can re-render after every milestone if you want.
    """

    def __init__(
        self,
        *,
        title: str = "bioflow report",
        out_dir: Path,
        subtitle: str = "",
    ):
        self.title = title
        self.subtitle = subtitle
        self.out_dir = Path(out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "figures").mkdir(exist_ok=True)
        self._sections: list[_Section] = []
        self._created_at = datetime.datetime.now()

    # ------------------------------------------------------------------
    # Public builder API
    # ------------------------------------------------------------------
    def add_text(self, text: str) -> None:
        """Append a free-form HTML paragraph (text is escaped first)."""
        self._sections.append(
            _Section(title="", html=f"<p>{html.escape(text)}</p>")
        )

    def add_section(
        self,
        title: str,
        *,
        body: str = "",
        results: Optional[Iterable] = None,
        code: Optional[str] = None,
    ) -> None:
        """Add a labelled section.

        Parameters
        ----------
        title :
            Section heading.
        body :
            Plain-text description; rendered as a paragraph (escaped).
        results :
            Iterable of :class:`bioflow.StageResult`.  Rendered as a small
            chip line showing total / cached / failed counts plus the
            first few out_dirs.
        code :
            Optional code block (escaped, monospace).
        """
        parts: list[str] = []
        if body:
            parts.append(f"<p>{html.escape(body)}</p>")
        if results is not None:
            parts.append(self._render_results(list(results)))
        if code:
            parts.append(
                f"<pre><code>{html.escape(code)}</code></pre>"
            )
        self._sections.append(
            _Section(title=title, html="\n".join(parts))
        )

    def add_figure(
        self,
        title: str,
        fig: Any,
        *,
        caption: str = "",
        filename: Optional[str] = None,
    ) -> Path:
        """Save *fig* as PNG into ``<out_dir>/figures/`` and embed it.

        *fig* should be a Matplotlib ``Figure``.  Returns the saved path.
        """
        if filename is None:
            slug = "".join(
                c if c.isalnum() else "_" for c in title.lower()
            ).strip("_") or f"fig_{len(self._sections)}"
            filename = f"{slug}.png"
        path = self.out_dir / "figures" / filename
        try:
            fig.savefig(path, dpi=130, bbox_inches="tight")
        except Exception as exc:
            log.warning(f"Could not save figure {title!r}: {exc}")
            self.add_section(
                title, body=f"[figure save failed: {exc}]"
            )
            return path

        rel = f"figures/{filename}"
        body_html = f'<img src="{html.escape(rel)}" alt="{html.escape(title)}">'
        if caption:
            body_html += f'<p class="caption">{html.escape(caption)}</p>'
        self._sections.append(_Section(title=title, html=body_html))
        return path

    def add_table(
        self,
        title: str,
        table: Any,
        *,
        caption: str = "",
        max_rows: int = 50,
    ) -> None:
        """Render a pandas DataFrame (or HTML-able object) as a table.

        For large frames, only the top *max_rows* rows are shown along
        with a "(N rows truncated)" note.
        """
        try:
            n_rows = len(table)
            sub = table.head(max_rows) if n_rows > max_rows else table
            table_html = sub.to_html(
                index=False, classes="data", border=0, escape=True,
            )
        except Exception as exc:
            self.add_section(
                title, body=f"[table render failed: {exc}]"
            )
            return

        cap = (
            f'<p class="caption">{html.escape(caption)}</p>' if caption else ""
        )
        truncation = (
            f'<p class="muted">{n_rows - max_rows} rows truncated</p>'
            if n_rows > max_rows else ""
        )
        self._sections.append(
            _Section(title=title, html=table_html + truncation + cap)
        )

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def write(self, path: Optional[Path] = None) -> Path:
        """Render to HTML.  Default path: ``<out_dir>/summary.html``."""
        target = Path(path) if path else self.out_dir / "summary.html"
        target.parent.mkdir(parents=True, exist_ok=True)

        sections_html = "\n".join(
            self._render_section(i, s)
            for i, s in enumerate(self._sections, 1)
        )
        page = _PAGE_TEMPLATE.format(
            title=html.escape(self.title),
            subtitle=html.escape(self.subtitle),
            now=self._created_at.strftime("%Y-%m-%d %H:%M"),
            sections=sections_html,
            n_sections=len(self._sections),
        )
        # Always LF — avoid the CRLF quirk that bit us with CAFE5.
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(page)
        log.info(f"Report written → {target}")
        return target

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _render_section(self, idx: int, s: _Section) -> str:
        if not s.title:
            return f'<div class="section">{s.html}</div>'
        ts = s.timestamp.strftime("%H:%M:%S")
        return (
            f'<div class="section">'
            f'<h2><span class="num">{idx}.</span> {html.escape(s.title)} '
            f'<span class="ts">{ts}</span></h2>\n{s.html}\n</div>'
        )

    def _render_results(self, results: list) -> str:
        if not results:
            return '<p class="muted">(no stage results to summarise)</p>'
        n = len(results)
        n_cached = sum(1 for r in results if getattr(r, "cached", False))
        n_failed = sum(1 for r in results if not getattr(r, "ok", False))
        sample_dirs = [
            html.escape(str(r.out_dir))
            for r in results[:5] if hasattr(r, "out_dir")
        ]
        more = f" + {n - 5} more" if n > 5 else ""
        chip = (
            f'<p class="chip">{n} stage results · '
            f'<span class="ok">cached={n_cached}</span> · '
            f'<span class="{"err" if n_failed else "ok"}">failed={n_failed}</span></p>'
        )
        list_html = (
            "<ul class=\"dirs\">"
            + "".join(f"<li><code>{d}</code></li>" for d in sample_dirs)
            + (f"<li><i>{more}</i></li>" if more else "")
            + "</ul>"
        )
        return chip + list_html


# ---------------------------------------------------------------------------
# HTML scaffolding
# ---------------------------------------------------------------------------

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{title}</title>
<style>
 body {{ font-family: -apple-system, "Segoe UI", sans-serif;
        max-width: 1100px; margin: 2em auto; padding: 0 20px; color:#222 }}
 h1 {{ color:#1f3a93; border-bottom: 2px solid #1f3a93; padding-bottom: 4px }}
 h2 {{ color:#1f3a93; margin-top: 1.6em }}
 h2 .num  {{ color:#aaa; margin-right:6px }}
 h2 .ts   {{ color:#aaa; font-size:0.6em; margin-left:8px; font-weight:normal }}
 .section {{ border-left: 3px solid #ddd; padding: 0 16px; margin: 16px 0 }}
 img      {{ max-width:100%; height:auto; display:block; margin:10px auto }}
 table.data {{ border-collapse: collapse; font-size: 0.9em; margin:8px 0 }}
 table.data th, table.data td {{ padding:4px 10px; border-bottom:1px solid #ddd; text-align:left }}
 table.data th {{ background:#eef }}
 pre  {{ background:#f4f4f4; padding:10px; overflow-x:auto; border-radius:4px }}
 code {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size:0.9em }}
 .muted   {{ color:#777; font-size:0.85em }}
 .caption {{ color:#555; font-size:0.85em; font-style:italic }}
 .chip    {{ background:#f0f4ff; padding:6px 12px; border-radius:4px;
            display:inline-block; font-size:0.9em }}
 .ok  {{ color:#1a7f37 }}
 .err {{ color:#c0392b }}
 .dirs li code {{ background:#f4f4f4; padding:1px 4px; border-radius:3px }}
</style></head><body>
<h1>{title}</h1>
{subtitle}
<p class="muted">Generated by bioflow on {now} · {n_sections} sections</p>
{sections}
</body></html>
"""
