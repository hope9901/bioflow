"""Registry promotion — approve a candidate tool YAML.

``bioflow update approve <candidate.yaml> [--registry registry]``

Workflow
--------
1. Load and validate the candidate YAML against ``registry/schema.yaml``
   (``update_meta`` block is stripped before validation).
2. Determine the destination path:
   ``<registry_dir>/tools/<category>/<id>.yaml``
3. Check for conflicts (tool with same id already in registry).
4. Write the clean YAML (without ``update_meta``) to the registry.
5. Append an entry to ``update/CHANGELOG.md``.
6. Print a summary.

The function never modifies the source candidate file and never deletes
anything — if you want to remove the candidate after approval, delete it
manually (or the CLI caller can do it with ``--delete-candidate``).
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

import yaml

from bioflow.core.logger import get_logger

log = get_logger()

_DEFAULT_CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "update" / "CHANGELOG.md"


def _changelog_path_for(registry_dir: Path) -> Path:
    """Resolve the CHANGELOG.md location relative to the given registry root.

    Tests pass a tmp registry dir — we route the CHANGELOG to a sibling
    ``update/`` so test runs never touch the project's real CHANGELOG.
    Production callers using the project's real registry get the original
    ``<repo>/update/CHANGELOG.md`` path.
    """
    candidate = registry_dir.resolve().parent / "update" / "CHANGELOG.md"
    # If the registry sits at the project root, the candidate IS the default.
    return candidate if candidate.parent.parent.exists() else _DEFAULT_CHANGELOG_PATH


# Backwards-compatibility alias for callers/tests that import it directly.
CHANGELOG_PATH = _DEFAULT_CHANGELOG_PATH


class ApprovalError(Exception):
    """Raised when approval cannot proceed safely."""


def approve_candidate(
    candidate_path: Path,
    *,
    registry_dir: Path = Path("registry"),
    overwrite: bool = False,
    delete_candidate: bool = False,
    dry_run: bool = False,
) -> Path:
    """Promote a candidate YAML to the tool registry.

    Parameters
    ----------
    candidate_path:
        Path to the candidate ``.yaml`` file (may contain ``update_meta``).
    registry_dir:
        Root of the tool registry (default ``registry``).
    overwrite:
        Allow overwriting an existing registry entry.
    delete_candidate:
        Remove the candidate file after successful promotion.
    dry_run:
        Print what would happen without writing anything.

    Returns
    -------
    Path
        The registry destination path.

    Raises
    ------
    ApprovalError
        When validation fails or a conflict is detected and ``overwrite``
        is ``False``.
    """
    if not candidate_path.exists():
        raise ApprovalError(f"Candidate file not found: {candidate_path}")

    # 1. Load + strip update_meta
    raw = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    update_meta: dict = raw.pop("update_meta", {})

    # 2. Validate against schema
    schema_path = registry_dir / "schema.yaml"
    if not schema_path.exists():
        raise ApprovalError(f"Registry schema not found: {schema_path}")
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))

    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        raise ApprovalError(
            "jsonschema is required for tool approval: pip install jsonschema. "
            "Skipping validation would allow invalid tool definitions into the "
            "registry and break pipelines at runtime."
        )

    try:
        jsonschema.validate(instance=raw, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ApprovalError(f"Schema validation failed: {exc.message}") from exc

    tool_id: str = raw["id"]
    category: str = raw["category"]

    # 3. Resolve destination
    dest = registry_dir / "tools" / category / f"{tool_id}.yaml"

    if dest.exists() and not overwrite:
        raise ApprovalError(
            f"Tool '{tool_id}' already exists at {dest}. "
            f"Use --overwrite to replace it."
        )

    if dry_run:
        log.info(
            f"[DRY RUN] Would write {candidate_path.name} → {dest}"
        )
        return dest

    # 4. Write clean YAML
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as fh:
        yaml.dump(raw, fh, allow_unicode=True, sort_keys=False)
    log.info(f"Approved: {tool_id} → {dest}")

    # 5. Append CHANGELOG (sibling of the registry — test registries get
    # an isolated CHANGELOG so they cannot pollute the project's real one)
    _append_changelog(
        tool_id, category, update_meta, candidate_path,
        changelog_path=_changelog_path_for(registry_dir),
    )

    # 6. Optionally delete candidate
    if delete_candidate:
        candidate_path.unlink()
        log.info(f"Deleted candidate: {candidate_path}")

    return dest


def approve_all_candidates(
    candidates_dir: Path,
    *,
    registry_dir: Path = Path("registry"),
    overwrite: bool = False,
    delete_candidates: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    """Approve every ``.yaml`` in *candidates_dir*.

    Returns a list of result dicts with keys:
    ``file``, ``status`` (``"approved"`` | ``"skipped"`` | ``"error"``),
    ``dest`` (on success), ``error`` (on failure).
    """
    yamls = sorted(candidates_dir.glob("*.yaml"))
    if not yamls:
        log.warning(f"No candidate YAML files found in {candidates_dir}")
        return []

    results: list[dict] = []
    for path in yamls:
        try:
            dest = approve_candidate(
                path,
                registry_dir=registry_dir,
                overwrite=overwrite,
                delete_candidate=delete_candidates,
                dry_run=dry_run,
            )
            results.append({"file": path.name, "status": "approved", "dest": str(dest)})
        except ApprovalError as exc:
            log.warning(f"Skipped {path.name}: {exc}")
            results.append({"file": path.name, "status": "skipped", "error": str(exc)})
        except Exception as exc:
            log.error(f"Error approving {path.name}: {exc}")
            results.append({"file": path.name, "status": "error", "error": str(exc)})

    return results


# ---------------------------------------------------------------------------
# CHANGELOG helper
# ---------------------------------------------------------------------------

def _append_changelog(
    tool_id: str,
    category: str,
    update_meta: dict,
    source: Path,
    *,
    changelog_path: Optional[Path] = None,
) -> None:
    month = update_meta.get("month") or datetime.date.today().strftime("%Y-%m")
    replaces = update_meta.get("replaces") or []
    benchmark_note = update_meta.get("benchmark_note", "")
    risks = update_meta.get("risks", [])

    lines = [
        f"\n### {month} — {tool_id}",
        f"- **category**: {category}",
        f"- **source**: `{source.name}`",
    ]
    if replaces:
        lines.append(f"- **replaces**: {', '.join(replaces)}")
    if benchmark_note:
        lines.append(f"- **benchmark**: {benchmark_note}")
    if risks:
        for r in risks:
            lines.append(f"- **risk**: {r}")

    entry = "\n".join(lines) + "\n"

    changelog = changelog_path or CHANGELOG_PATH
    changelog.parent.mkdir(parents=True, exist_ok=True)
    if not changelog.exists():
        changelog.write_text("# Registry changelog\n", encoding="utf-8")

    with changelog.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    log.info(f"CHANGELOG updated ({changelog})")
