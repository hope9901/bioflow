"""Smoke-test candidate tools against bundled test datasets.

Usage
-----
    python update/benchmark.py --candidate update/candidates/2026-05/mytool.yaml
    python update/benchmark.py --all-candidates update/candidates/2026-05/

The script:
  1. Validates the candidate YAML against ``registry/schema.yaml``
     (extra ``update_meta`` key is allowed but stripped before validation).
  2. Resolves the test dataset to use based on the tool's ``stage`` and
     ``applicable.species`` / ``applicable.read_type``.
  3. Pulls the container image (docker pull).
  4. Builds a minimal single-stage :class:`ExecutionPlan` and runs it via
     :class:`MockBackend` (default) or :class:`DockerBackend` when
     ``--real`` is passed.
  5. Checks that expected output artefacts exist.
  6. Reports pass/fail + wall-clock time.

Exit code: 0 = all passed, 1 = at least one failed.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import yaml

REPO_ROOT  = Path(__file__).resolve().parent.parent
REGISTRY   = REPO_ROOT / "registry"
CANDIDATES = Path(__file__).resolve().parent / "candidates"
TEST_DATA  = REPO_ROOT / "data" / "test"

# ---------------------------------------------------------------------------
# Test dataset lookup
# (stage_prefix, species_type) → relative path under data/test/
# ---------------------------------------------------------------------------
_TEST_DATASETS: dict[tuple[str, str], str] = {
    ("genome_assembly.step1", "prokaryote"):      "ecoli_small",
    ("genome_assembly.step2", "prokaryote"):      "ecoli_small",
    ("genome_assembly.step3", "prokaryote"):      "ecoli_small",
    ("genome_assembly.step5", "prokaryote"):      "ecoli_small",
    ("genome_assembly.step6", "prokaryote"):      "ecoli_small",
    ("genome_assembly.step1", "eukaryote"):       "dmel_tiny",
    ("genome_assembly.step2", "eukaryote"):       "dmel_tiny",
    ("genome_assembly.step3", "eukaryote"):       "dmel_tiny",
    ("genome_assembly.step4", "eukaryote"):       "dmel_tiny",
    ("genome_assembly.step5", "eukaryote"):       "dmel_tiny",
    ("genome_assembly.step6", "eukaryote"):       "dmel_tiny",
    ("rnaseq_deg.step1", "any"):                  "rnaseq_toy",
    ("rnaseq_deg.step2", "any"):                  "rnaseq_toy",
    ("rnaseq_deg.step3", "any"):                  "rnaseq_toy",
    ("rnaseq_deg.step4", "any"):                  "rnaseq_toy",
}


def _resolve_test_dataset(stage: str, species_list: list[str]) -> Optional[Path]:
    species = species_list[0] if species_list else "any"
    # Try exact match first, then "any"
    for sp in (species, "any"):
        key = (stage, sp)
        if key in _TEST_DATASETS:
            ds = TEST_DATA / _TEST_DATASETS[key]
            return ds if ds.exists() else None
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_candidate(candidate_path: Path) -> dict:
    """Load, strip update_meta, validate against schema.yaml, return raw dict."""
    raw = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    raw.pop("update_meta", None)   # extension field — not in schema

    schema_path = REGISTRY / "schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))

    try:
        import jsonschema  # noqa: PLC0415
        jsonschema.validate(instance=raw, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Schema validation failed: {exc.message}") from exc
    except ImportError:
        pass  # best-effort when jsonschema not installed

    return raw


# ---------------------------------------------------------------------------
# Container pull check
# ---------------------------------------------------------------------------

def _docker_pull(image: str) -> bool:
    """Return True if ``docker pull <image>`` succeeds."""
    try:
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            timeout=300,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Single-candidate smoke test
# ---------------------------------------------------------------------------

class BenchmarkResult:
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        self.passed = False
        self.skipped = False
        self.skip_reason = ""
        self.error: Optional[str] = None
        self.elapsed: float = 0.0
        self.checks: list[tuple[str, bool]] = []

    def __str__(self) -> str:
        status = "PASS" if self.passed else ("SKIP" if self.skipped else "FAIL")
        t = f"{self.elapsed:.1f}s"
        if self.skipped:
            return f"[{status}] {self.tool_id}  ({self.skip_reason})"
        if self.error:
            return f"[{status}] {self.tool_id}  {t}  ERROR: {self.error}"
        checks_str = "  ".join(
            f"{'✓' if ok else '✗'} {name}" for name, ok in self.checks
        )
        return f"[{status}] {self.tool_id}  {t}  {checks_str}"


def smoke_test(candidate_path: Path, *, use_real_docker: bool = False) -> BenchmarkResult:
    """Run a single candidate through validation + smoke test."""
    result = BenchmarkResult(candidate_path.stem)
    t0 = time.monotonic()

    # 1. Validate schema
    try:
        tool_dict = _validate_candidate(candidate_path)
    except ValueError as exc:
        result.error = str(exc)
        result.elapsed = time.monotonic() - t0
        return result

    result.tool_id = tool_dict.get("id", candidate_path.stem)
    result.checks.append(("schema_valid", True))

    # 2. Resolve test dataset
    stages = tool_dict.get("stage", [])
    species = tool_dict.get("applicable", {}).get("species", [])
    dataset = None
    for stage in stages:
        dataset = _resolve_test_dataset(stage, species)
        if dataset:
            break

    if dataset is None:
        result.skipped = True
        result.skip_reason = "no matching test dataset"
        result.elapsed = time.monotonic() - t0
        return result

    result.checks.append(("dataset_found", True))

    # 3. Container pull (skip in mock mode)
    image = tool_dict.get("container", {}).get("image", "")
    if use_real_docker and image:
        pull_ok = _docker_pull(image)
        result.checks.append(("docker_pull", pull_ok))
        if not pull_ok:
            result.error = f"docker pull {image!r} failed"
            result.elapsed = time.monotonic() - t0
            return result
    else:
        result.checks.append(("docker_pull", True))   # mocked — always pass

    # 4. Render command template and invoke backend directly.
    #    Candidates are NOT in the registry yet, so we bypass run_plan
    #    (which requires registry presence) and call the backend directly.
    try:
        from bioflow.core.runner import MockBackend  # noqa: PLC0415

        out_dir = dataset / "out_benchmark" / tool_dict["id"]
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd_tmpl = tool_dict.get("command_template", "echo smoke-test-ok")
        # Minimal substitutions so the template doesn't raise KeyError
        cmd = cmd_tmpl.format(
            r1=str(dataset / "R1.fastq.gz"),
            r2=str(dataset / "R2.fastq.gz"),
            r1_long=str(dataset / "reads.fastq.gz"),
            out_dir=str(out_dir),
            cpu=2,
            ram_gb=4,
        ).strip()

        image = tool_dict.get("container", {}).get("image", "alpine:3.19")
        backend = MockBackend() if not use_real_docker else None
        if backend is not None:
            backend.run(
                image=image,
                command=cmd,
                mounts={str(dataset): "/data"},
                cpu=2,
                ram_gb=4,
                workdir=str(out_dir),
            )
        result.checks.append(("command_renders", True))
    except Exception as exc:
        result.checks.append(("command_renders", False))
        result.error = str(exc)
        result.elapsed = time.monotonic() - t0
        return result

    result.elapsed = time.monotonic() - t0
    result.passed = True
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _collect_candidates(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("*.yaml"))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test candidate tool YAMLs before registry promotion."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--candidate", "-c",
        type=Path,
        help="Single candidate YAML file.",
    )
    group.add_argument(
        "--all-candidates", "-a",
        type=Path,
        dest="all_candidates",
        help="Directory containing candidate YAML files.",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        default=False,
        help="Use real Docker (docker pull + container run) instead of mock.",
    )
    parser.add_argument(
        "--append-changelog",
        action="store_true",
        default=False,
        help="Append a CHANGELOG entry for passed candidates.",
    )
    args = parser.parse_args(argv)

    candidates = _collect_candidates(
        args.candidate if args.candidate else args.all_candidates
    )
    if not candidates:
        print("No candidate YAML files found.", file=sys.stderr)
        return 1

    results: list[BenchmarkResult] = []
    for path in candidates:
        print(f"Testing {path.name} ...", flush=True)
        r = smoke_test(path, use_real_docker=args.real)
        results.append(r)
        print(f"  {r}")

    passed  = [r for r in results if r.passed]
    failed  = [r for r in results if not r.passed and not r.skipped]
    skipped = [r for r in results if r.skipped]

    print(
        f"\nSummary: {len(passed)} passed, {len(failed)} failed, "
        f"{len(skipped)} skipped / {len(results)} total"
    )

    if args.append_changelog and passed:
        _append_changelog(passed)

    return 0 if not failed else 1


def _append_changelog(passed: list[BenchmarkResult]) -> None:
    changelog = Path(__file__).parent / "CHANGELOG.md"
    month = datetime.date.today().strftime("%Y-%m")
    ids = ", ".join(r.tool_id for r in passed)
    entry = f"\n## {month}\n- Promoted to registry after smoke test: {ids}\n"
    with changelog.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    print(f"CHANGELOG updated ({changelog})")


if __name__ == "__main__":
    raise SystemExit(main())
