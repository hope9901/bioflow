"""Cohort runner — fan a single-sample recipe across a samplesheet.

Many recipes process one sample per call (``prokaryote_assembly``,
``germline_variants``, ``metagenomics_profile``, ``methylation_wgbs``, …).
This module runs such a recipe across every row of a CSV samplesheet, each
in its own workspace, optionally in parallel, then aggregates per-sample QC
with MultiQC.

Each sample runs as an isolated ``bioflow recipe run`` subprocess.  The SDK's
active workspace + backend are process-global state, so subprocess isolation
is what makes parallel samples safe — and it yields a clean per-sample log
and exit code for free.  Recipes that already loop over a samplesheet
internally (``rnaseq_deg``, ``joint_genotyping``) are *not* the use case here.
"""
from __future__ import annotations

import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from bioflow.core.logger import get_logger

log = get_logger()

# Accepted sample-identifier column names (case-insensitive, first match wins).
_ID_COLUMNS = ("sample_id", "sample", "id", "name")


@dataclass
class SampleResult:
    sample_id: str
    ok: bool
    returncode: int
    workspace: Path
    log_path: Optional[Path] = None
    error: str = ""


@dataclass
class CohortReport:
    recipe: str
    out_dir: Path
    results: "list[SampleResult]" = field(default_factory=list)
    multiqc_report: Optional[Path] = None

    @property
    def n_ok(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def n_failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def ok(self) -> bool:
        return bool(self.results) and self.n_failed == 0


def read_samplesheet(path: Path) -> "list[dict[str, str]]":
    """Read a CSV samplesheet into a list of per-sample param dicts.

    One column identifies the sample (``sample_id`` / ``sample`` / ``id`` /
    ``name``, case-insensitive) and is normalised to ``sample_id``; the rest
    become per-sample recipe parameters.  Blank values are dropped; duplicate
    or empty sample ids raise.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"Samplesheet {path} has no header row.")
        lower = {c.lower(): c for c in reader.fieldnames}
        id_col = next((lower[c] for c in _ID_COLUMNS if c in lower), None)
        if id_col is None:
            raise ValueError(
                f"Samplesheet {path} needs a sample-id column (one of: "
                f"{', '.join(_ID_COLUMNS)}).  Got: {reader.fieldnames}"
            )
        rows: "list[dict[str, str]]" = []
        seen: "set[str]" = set()
        for raw in reader:
            sid = (raw.get(id_col) or "").strip()
            if not sid or sid.startswith("#"):
                continue
            if sid in seen:
                raise ValueError(f"Duplicate sample_id {sid!r} in {path}.")
            seen.add(sid)
            row = {"sample_id": sid}
            for col, val in raw.items():
                if col is None or col == id_col:
                    continue
                if val is not None and str(val).strip():
                    row[col.strip()] = str(val).strip()
            rows.append(row)
    if not rows:
        raise ValueError(f"Samplesheet {path} has no data rows.")
    return rows


def _flagify(params: "dict[str, str]") -> "list[str]":
    """Turn ``{key: value}`` into ``['--key', 'value', …]`` for the CLI."""
    argv: "list[str]" = []
    for k, v in params.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return argv


def _run_one_subprocess(
    recipe: str, sample_id: str, workspace: Path, params: "dict[str, str]",
) -> SampleResult:
    """Default per-sample runner: an isolated ``bioflow recipe run`` subprocess."""
    workspace.mkdir(parents=True, exist_ok=True)
    log_path = workspace / "cohort_sample.log"
    argv = [
        sys.executable, "-m", "bioflow.cli", "recipe", "run", recipe,
        "--out", str(workspace), "--no-provenance",
        *_flagify({"sample_id": sample_id, **params}),
    ]
    with log_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, text=True)
    return SampleResult(
        sample_id=sample_id,
        ok=(proc.returncode == 0),
        returncode=proc.returncode,
        workspace=workspace,
        log_path=log_path,
        error="" if proc.returncode == 0 else f"exit {proc.returncode}; see {log_path}",
    )


def run_cohort(
    recipe: str,
    samplesheet: Path,
    out_dir: Path,
    *,
    common: "Optional[dict[str, str]]" = None,
    jobs: int = 1,
    aggregate: bool = True,
    run_one: "Optional[Callable[..., SampleResult]]" = None,
) -> CohortReport:
    """Run *recipe* across every sample in *samplesheet*.

    Each sample runs in ``out_dir/<sample_id>``.  ``common`` params are applied
    to every sample (e.g. a shared ``--reference``); per-sample columns take
    precedence.  Up to *jobs* samples run concurrently.  One sample failing
    does not abort the rest — the failure is recorded and the cohort continues.
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    common = common or {}
    run_one = run_one or _run_one_subprocess
    rows = read_samplesheet(Path(samplesheet))
    report = CohortReport(recipe=recipe, out_dir=out_dir)

    def _do(row: "dict[str, str]") -> SampleResult:
        sid = row["sample_id"]
        params = {**common, **{k: v for k, v in row.items() if k != "sample_id"}}
        ws = out_dir / sid
        log.info(f"COHORT {recipe} :: sample {sid} -> {ws}")
        try:
            return run_one(recipe, sid, ws, params)
        except Exception as exc:   # never let one sample kill the whole cohort
            return SampleResult(sid, False, 1, ws, error=str(exc))

    if jobs and jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futs = [pool.submit(_do, r) for r in rows]
            for fut in as_completed(futs):
                report.results.append(fut.result())
        report.results.sort(key=lambda r: r.sample_id)
    else:
        report.results = [_do(r) for r in rows]

    if aggregate and report.n_ok:
        report.multiqc_report = _aggregate(out_dir)
    return report


def _aggregate(out_dir: Path) -> "Optional[Path]":
    """Run MultiQC over every per-sample workspace → one cohort report."""
    try:
        from bioflow.core.report import run_multiqc  # noqa: PLC0415
        return run_multiqc(out_dir, out_dir / "cohort_multiqc")
    except Exception as exc:   # aggregation is best-effort, never fatal
        log.warning(f"Cohort MultiQC aggregation skipped: {exc}")
        return None
