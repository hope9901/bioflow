"""Run provenance — RO-Crate + PROV-style JSON for every recipe run.

Why
---
A bioflow recipe is only as trustworthy as its reproducibility story.
This module records, for each stage that executes:

* the container **image** and (best-effort) its content-addressed
  **digest**,
* the exact **command** string sent to the container,
* every **input file**'s SHA-256 + size,
* **start / end** timestamps and the exit code,
* the bioflow version that orchestrated the run.

At the end of a recipe the recorder writes two files into the workspace:

* ``provenance.json`` — a flat, human-readable run record, and
* ``ro-crate-metadata.json`` — an `RO-Crate <https://www.researchobject.org/ro-crate/>`_
  1.1 document (the de-facto packaging standard for computational
  workflow runs), so the output directory is a self-describing research
  object a journal reviewer or downstream tool can consume directly.

Design
------
* **Opt-in, zero-cost when off.**  A module-global *active recorder* is
  ``None`` until a run installs one.  :func:`record_stage` returns
  immediately when there is no active recorder, so the SDK hot path pays
  nothing unless provenance is enabled.
* **Never the reason a run fails.**  Hashing / digest resolution / file
  writes are wrapped so a provenance error degrades to a warning, never
  an exception that aborts the science.
* **Decoupled from the SDK.**  This module imports only the logger; the
  SDK imports *it*.  No cycle.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from bioflow.core.logger import get_logger

log = get_logger()

PROVENANCE_JSON = "provenance.json"
RO_CRATE_JSON = "ro-crate-metadata.json"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

@dataclass
class FileRef:
    path: str
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None

    def to_dict(self) -> dict:
        d: dict = {"path": self.path}
        if self.sha256:
            d["sha256"] = self.sha256
        if self.size_bytes is not None:
            d["size_bytes"] = self.size_bytes
        return d


@dataclass
class StageRecord:
    name: str
    image: str
    command: str
    exit_code: int
    cached: bool
    started_at: str
    ended_at: str
    out_dir: str
    inputs: list[FileRef] = field(default_factory=list)
    image_digest: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "image": self.image,
            "image_digest": self.image_digest,
            "command": self.command,
            "exit_code": self.exit_code,
            "cached": self.cached,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "out_dir": self.out_dir,
            "inputs": [f.to_dict() for f in self.inputs],
        }


class ProvenanceRecorder:
    """Accumulates :class:`StageRecord` entries for one recipe run."""

    def __init__(self, pipeline: str, workspace: Path) -> None:
        self.pipeline = pipeline
        self.workspace = Path(workspace)
        self.started_at = _now_iso()
        self.ended_at: Optional[str] = None
        self.stages: list[StageRecord] = []

    def add(self, record: StageRecord) -> None:
        self.stages.append(record)

    def finish(self) -> None:
        self.ended_at = _now_iso()

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "bioflow_version": _bioflow_version(),
            "pipeline": self.pipeline,
            "workspace": str(self.workspace),
            "started_at": self.started_at,
            "ended_at": self.ended_at or _now_iso(),
            "host": {
                "os": platform.system().lower(),
                "arch": platform.machine(),
                "python": platform.python_version(),
            },
            "stages": [s.to_dict() for s in self.stages],
        }


# ---------------------------------------------------------------------------
# Module-global active recorder (opt-in)
# ---------------------------------------------------------------------------

_active: Optional[ProvenanceRecorder] = None


def set_recorder(rec: Optional[ProvenanceRecorder]) -> None:
    global _active
    _active = rec


def get_recorder() -> Optional[ProvenanceRecorder]:
    return _active


def record_stage(
    *,
    name: str,
    image: str,
    command: str,
    exit_code: int,
    cached: bool,
    out_dir: Path,
    started_at: str,
    ended_at: str,
    args: tuple,
    kwargs: dict,
    backend: Any = None,
) -> None:
    """Append a stage record to the active recorder, if any.

    No-op (and never raises) when provenance is disabled.  All the
    expensive work — input hashing, digest resolution — happens here so
    it is only paid when a recorder is installed.
    """
    rec = _active
    if rec is None:
        return
    try:
        inputs = [
            FileRef(path=str(p), **_hash_and_size(p))
            for p in _collect_input_files(args, kwargs)
        ]
        digest = _resolve_image_digest(image, backend) if not cached else None
        rec.add(StageRecord(
            name=name,
            image=image,
            image_digest=digest,
            command=command,
            exit_code=exit_code,
            cached=cached,
            started_at=started_at,
            ended_at=ended_at,
            out_dir=str(out_dir),
            inputs=inputs,
        ))
    except Exception as exc:  # provenance must never break a run
        log.warning(f"provenance: failed to record stage {name!r}: {exc}")


# ---------------------------------------------------------------------------
# Hashing + input discovery
# ---------------------------------------------------------------------------

def sha256_file(path: Path, _chunk: int = 1 << 20) -> Optional[str]:
    """Full SHA-256 of a file, or None if unreadable."""
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for block in iter(lambda: fh.read(_chunk), b""):
                h.update(block)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def _hash_and_size(path: Path) -> dict:
    try:
        size = Path(path).stat().st_size
    except OSError:
        size = None
    return {"sha256": sha256_file(path), "size_bytes": size}


def _collect_input_files(args: tuple, kwargs: dict) -> list[Path]:
    """Existing regular-file ``Path`` inputs among the call arguments.

    Directories, the injected ``out_dir``, and ``StageResult`` objects
    (intermediate workspace artifacts) are skipped — provenance records
    the *primary* inputs the user supplied.
    """
    found: list[Path] = []
    seen: set[str] = set()

    def _scan(v: Any) -> None:
        if isinstance(v, Path):
            try:
                if v.is_file():
                    key = str(v.resolve())
                    if key not in seen:
                        seen.add(key)
                        found.append(v)
            except OSError:
                pass
        elif v.__class__.__name__ == "StageResult":
            return
        elif isinstance(v, (list, tuple, set)):
            for item in v:
                _scan(item)
        elif isinstance(v, dict):
            for item in v.values():
                _scan(item)

    for a in args:
        _scan(a)
    for k, v in kwargs.items():
        if k == "out_dir":
            continue
        _scan(v)
    return found


# ---------------------------------------------------------------------------
# Image digest resolution (best-effort)
# ---------------------------------------------------------------------------

def _resolve_image_digest(image: str, backend: Any = None) -> Optional[str]:
    """Resolve *image*'s content digest from the local Docker image.

    Best-effort: returns None on the MockBackend, when docker is absent,
    or when the image has no RepoDigest yet.  If the image string is
    already digest-pinned (``repo@sha256:…``) that digest is returned
    directly.
    """
    if "@sha256:" in image:
        return image.split("@", 1)[1]
    # Skip the docker call for non-Docker backends (e.g. MockBackend in
    # tests) so provenance stays fast and offline there.
    if backend is not None and not getattr(backend, "_STREAMING_SUPPORTED", False):
        return None
    if shutil.which("docker") is None:
        return None
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if r.returncode != 0:
            return None
        repo_digests = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    for rd in repo_digests:
        if "@sha256:" in rd:
            return rd.split("@", 1)[1]
    return None


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_all(rec: ProvenanceRecorder) -> list[Path]:
    """Write provenance.json + ro-crate-metadata.json into the workspace."""
    rec.finish()
    written: list[Path] = []
    for writer in (write_provenance_json, write_ro_crate):
        try:
            written.append(writer(rec))
        except Exception as exc:
            log.warning(f"provenance: {writer.__name__} failed: {exc}")
    return written


def write_provenance_json(rec: ProvenanceRecorder) -> Path:
    target = rec.workspace / PROVENANCE_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(rec.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    log.info(f"provenance -> {target}")
    return target


def write_ro_crate(rec: ProvenanceRecorder) -> Path:
    """Emit a minimal RO-Crate 1.1 metadata document.

    Models the run as a root Dataset that ``hasPart`` one ``CreateAction``
    per stage; each action ``instrument`` is a ``SoftwareApplication``
    (the container image) and its ``object`` list references the input
    ``File`` entities (with content SHA-256).
    """
    target = rec.workspace / RO_CRATE_JSON
    graph: list[dict] = []

    # Metadata file descriptor (required by the spec)
    graph.append({
        "@type": "CreativeWork",
        "@id": "ro-crate-metadata.json",
        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        "about": {"@id": "./"},
    })

    # Collect File + SoftwareApplication entities, de-duplicated by @id.
    file_entities: dict[str, dict] = {}
    app_entities: dict[str, dict] = {}
    action_ids: list[dict] = []

    for i, s in enumerate(rec.stages):
        action_id = f"#stage-{i}-{s.name}"
        app_id = f"#image-{s.image}"
        if app_id not in app_entities:
            app = {
                "@type": "SoftwareApplication",
                "@id": app_id,
                "name": s.image,
            }
            if s.image_digest:
                app["softwareVersion"] = s.image_digest
            app_entities[app_id] = app

        obj_refs = []
        for f in s.inputs:
            fid = f.path
            if fid not in file_entities:
                fe: dict = {"@type": "File", "@id": fid}
                if f.sha256:
                    fe["sha256"] = f.sha256
                if f.size_bytes is not None:
                    fe["contentSize"] = f.size_bytes
                file_entities[fid] = fe
            obj_refs.append({"@id": fid})

        graph.append({
            "@type": "CreateAction",
            "@id": action_id,
            "name": s.name,
            "instrument": {"@id": app_id},
            "object": obj_refs,
            "startTime": s.started_at,
            "endTime": s.ended_at,
            "actionStatus": (
                "http://schema.org/CompletedActionStatus" if s.exit_code == 0
                else "http://schema.org/FailedActionStatus"
            ),
            "result": [{"@id": s.out_dir}],
        })
        action_ids.append({"@id": action_id})

    # Root dataset
    graph.append({
        "@type": "Dataset",
        "@id": "./",
        "name": f"bioflow run: {rec.pipeline}",
        "description": (
            f"Provenance for the bioflow '{rec.pipeline}' recipe, "
            f"orchestrated by bioflow {_bioflow_version()}."
        ),
        "datePublished": rec.ended_at or _now_iso(),
        "hasPart": action_ids,
    })

    graph.extend(app_entities.values())
    graph.extend(file_entities.values())

    doc = {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    log.info(f"ro-crate -> {target}")
    return target


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _bioflow_version() -> str:
    try:
        import bioflow  # noqa: PLC0415
        return getattr(bioflow, "__version__", "unknown")
    except Exception:
        return "unknown"
