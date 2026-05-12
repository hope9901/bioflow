"""Pipeline reporting — MultiQC integration and HTML summary.

Responsibilities
----------------
1. ``run_multiqc(workdir, out_dir)``
   Launch the MultiQC container (quay.io/biocontainers/multiqc) as a sibling
   container and aggregate all QC artefacts under *workdir* into a single
   MultiQC HTML report written to *out_dir/multiqc_report.html*.

2. ``render_summary(plan, out_dir)``
   Write a lightweight *pipeline_summary.html* that lists each stage, the
   chosen tool, its output files, and links to log files.  Produced even when
   MultiQC is not available (no Docker required).

Design notes
------------
* Both functions are side-effect free with respect to the in-memory plan.
* ``run_multiqc`` may raise ``RuntimeError`` if Docker is not available; the
  caller should catch and warn rather than hard-abort the whole pipeline.
* ``render_summary`` has **no external dependencies** — it uses only stdlib
  ``string.Template`` so it works in the core container without extra packages.
"""

from __future__ import annotations

import datetime
import html
import json
from pathlib import Path
from string import Template
from typing import Optional

from bioflow.core.logger import get_logger
from bioflow.core.planner import ExecutionPlan

log = get_logger()

# ---------------------------------------------------------------------------
# MultiQC
# ---------------------------------------------------------------------------

MULTIQC_IMAGE = "quay.io/biocontainers/multiqc:1.21--pyhdfd78af_0"


def run_multiqc(
    workdir: Path,
    out_dir: Path,
    *,
    backend=None,                  # ContainerBackend; None → auto-detect Docker
    timeout: int = 600,
) -> Optional[Path]:
    """Run MultiQC over all QC artefacts under *workdir*.

    Returns the path to ``multiqc_report.html`` on success, or ``None`` if
    Docker is unavailable (a warning is logged).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if backend is None:
        try:
            from bioflow.core.runner import DockerBackend  # noqa: PLC0415
            backend = DockerBackend()
        except Exception as exc:
            log.warning(f"MultiQC skipped — Docker unavailable: {exc}")
            return None

    cmd = (
        "multiqc /data/workdir --outdir /data/out "
        "--filename multiqc_report.html --force --quiet"
    )

    log.info(f"MultiQC: scanning {workdir} -> {out_dir}")
    try:
        backend.run(
            image=MULTIQC_IMAGE,
            command=cmd,
            mounts={
                str(workdir): "/data/workdir",
                str(out_dir): "/data/out",
            },
            cpu=1,
            ram_gb=2,
            workdir="/data/out",
        )
    except Exception as exc:
        log.warning(f"MultiQC container failed: {exc}")
        return None

    report = out_dir / "multiqc_report.html"
    if report.exists():
        log.info(f"MultiQC report written to {report}")
        return report

    log.warning("MultiQC ran but report file not found")
    return None


# ---------------------------------------------------------------------------
# HTML summary template
# ---------------------------------------------------------------------------

_SUMMARY_TMPL = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>bioflow — $pipeline pipeline summary</title>
  <style>
    body { font-family: sans-serif; max-width: 960px; margin: 2rem auto; color: #222; }
    h1   { color: #2c7be5; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; }
    th { background: #f4f6fa; }
    tr:nth-child(even) { background: #fafafa; }
    .ok    { color: #28a745; font-weight: bold; }
    .skip  { color: #6c757d; }
    .warn  { color: #ffc107; font-weight: bold; }
    .err   { color: #dc3545; font-weight: bold; }
    .meta  { font-size: 0.85rem; color: #555; margin-top: 0.25rem; }
    a      { color: #2c7be5; }
  </style>
</head>
<body>
  <h1>bioflow pipeline summary</h1>
  <p class="meta">
    Pipeline: <strong>$pipeline</strong> &nbsp;|&nbsp;
    Preset: <strong>$preset</strong> &nbsp;|&nbsp;
    Species: <strong>$species</strong> &nbsp;|&nbsp;
    Read type: <strong>$read_type</strong> &nbsp;|&nbsp;
    Mode: <strong>$mode</strong><br>
    Generated: $generated
  </p>
  $multiqc_link
  <table>
    <thead>
      <tr>
        <th>#</th><th>Stage</th><th>Tool</th><th>Output directory</th>
        <th>Key outputs</th><th>Status</th>
      </tr>
    </thead>
    <tbody>
      $rows
    </tbody>
  </table>
</body>
</html>
""")

_ROW_TMPL = Template("""\
      <tr>
        <td>$idx</td>
        <td><code>$stage_id</code></td>
        <td><code>$tool_id</code></td>
        <td><code>$stage_dir</code></td>
        <td>$outputs</td>
        <td class="$status_cls">$status_label$error_detail</td>
      </tr>""")


def _status_from_checkpoint(stage_id: str, workdir: Path) -> tuple:
    """Return (css_class, label, error_detail) based on checkpoint state."""
    state_file = workdir / ".bioflow_state.json"
    if not state_file.exists():
        return ("skip", "not run", "")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if stage_id in state.get("completed_stages", []):
            return ("ok", "&#10003; done", "")
        failed = state.get("failed_stages", {}).get(stage_id)
        if failed:
            err = failed.get("error", "")
            return ("err", "&#10007; failed", err)
        return ("skip", "pending", "")
    except Exception:
        return ("warn", "unknown", "")


def render_summary(
    plan: ExecutionPlan,
    out_dir: Path,
    *,
    multiqc_report: Optional[Path] = None,
) -> Path:
    """Write a self-contained HTML pipeline summary to *out_dir/pipeline_summary.html*.

    Parameters
    ----------
    plan:
        The executed (or planned) :class:`ExecutionPlan`.
    out_dir:
        Directory where the HTML file will be written (created if absent).
    multiqc_report:
        If provided, a hyperlink to the MultiQC report is inserted at the top
        of the summary.

    Returns
    -------
    Path
        Absolute path of the written HTML file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = plan.workdir

    rows: list[str] = []
    for idx, stage in enumerate(plan.stages, start=1):
        stage_dir_path = workdir / stage.stage_id.replace(".", "_")
        # Collect key output filenames from params (values that look like file paths)
        output_files = [
            Path(v).name
            for v in stage.params.values()
            if isinstance(v, str) and Path(v).suffix
        ]
        outputs_html = "<br>".join(
            f"<code>{html.escape(str(f))}</code>" for f in output_files
        ) if output_files else "—"

        status_cls, status_label, error_detail = _status_from_checkpoint(
            stage.stage_id, workdir
        )
        error_html = (
            f'<br><small style="color:#dc3545;font-family:monospace">'
            f'{html.escape(str(error_detail)[:300])}</small>'
            if error_detail else ""
        )

        rows.append(
            _ROW_TMPL.substitute(
                idx=idx,
                stage_id=stage.stage_id,
                tool_id=stage.tool_id,
                stage_dir=str(stage_dir_path),
                outputs=outputs_html,
                status_cls=status_cls,
                status_label=status_label,
                error_detail=error_html,
            )
        )

    multiqc_link = ""
    if multiqc_report and multiqc_report.exists():
        try:
            rel = multiqc_report.relative_to(out_dir)
        except ValueError:
            rel = multiqc_report
        multiqc_link = (
            f'<p><a href="{rel}" target="_blank">&#128202; Open MultiQC report</a></p>'
        )

    rendered_html = _SUMMARY_TMPL.substitute(
        pipeline=plan.pipeline,
        preset=plan.preset or "custom",
        species=plan.species,
        read_type=plan.read_type,
        mode=plan.mode,
        generated=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        multiqc_link=multiqc_link,
        rows="\n".join(rows),
    )

    out_file = out_dir / "pipeline_summary.html"
    out_file.write_text(rendered_html, encoding="utf-8")
    log.info(f"Pipeline summary written to {out_file}")
    return out_file


# ---------------------------------------------------------------------------
# Convenience: run both in sequence
# ---------------------------------------------------------------------------

def generate_reports(
    plan: ExecutionPlan,
    out_dir: Optional[Path] = None,
    *,
    backend=None,
    skip_multiqc: bool = False,
) -> dict:
    """Run MultiQC (optional) then render the HTML summary.

    Returns a dict with keys ``"multiqc"`` and ``"summary"`` pointing to the
    respective output files (or ``None`` if not produced).
    """
    if out_dir is None:
        out_dir = plan.workdir / "reports"

    multiqc_path: Optional[Path] = None
    if not skip_multiqc:
        multiqc_path = run_multiqc(plan.workdir, out_dir, backend=backend)

    summary_path = render_summary(plan, out_dir, multiqc_report=multiqc_path)
    return {"multiqc": multiqc_path, "summary": summary_path}
