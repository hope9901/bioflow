"""Final report generation.

Runs MultiQC on the workdir and composes a bioflow summary HTML combining
per-stage metrics, tool versions, resource usage, and output paths.
"""

from __future__ import annotations

from pathlib import Path


def generate(workdir: Path) -> Path:
    """Produce <workdir>/report/bioflow_report.html. Implemented in step 9."""
    raise NotImplementedError("Implement in step 9.")
