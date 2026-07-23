"""Input/output staging for workers that cannot see the workspace.

Every backend so far (Docker, Apptainer, Slurm) bind-mounts the workspace, which
assumes the machine running the container can reach it — true locally and on an
HPC shared filesystem, false for a detached worker (cloud batch, Kubernetes with
no shared volume, a remote host). Those need inputs shipped out and outputs
shipped back.

The unit of staging is bioflow's **content-addressed out_dir**. Every stage
already writes to ``<workspace>/.cache/<stage>__<hash>``, which is immutable once
the stage succeeds — so the directory name is a ready-made object-store key that
dedupes across runs *and* across machines for free.

Staging is a **wrapper**, not another executor::

    StagingBackend(inner=DockerBackend(), store=LocalDirStore(scratch))
    StagingBackend(inner=SlurmBackend(),  store=LocalDirStore(scratch))

so it composes with wherever the job actually runs. Because the stage command is
already translated to ``/work/...`` paths, the sandbox only has to reproduce that
layout — no command rewriting is involved.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from bioflow.core.logger import get_logger
from bioflow.core.runner import CommandResult

log = get_logger()


@runtime_checkable
class ObjectStore(Protocol):
    """Somewhere both the submitter and the worker can reach.

    Keys are workspace-relative directory paths (e.g.
    ``.cache/align__3f21c9…``); values are whole directories.
    """

    def exists(self, key: str) -> bool: ...

    def push(self, local_dir: Path, key: str) -> None: ...

    def pull(self, key: str, local_dir: Path) -> bool: ...


class LocalDirStore:
    """Filesystem-backed :class:`ObjectStore`.

    Doubles as the verifiable stand-in for S3/GCS in tests and as a genuinely
    useful store when workers share a scratch filesystem that simply isn't
    mounted at the same path as the workspace.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self._path(key).is_dir()

    def push(self, local_dir: Path, key: str) -> None:
        dest = self._path(key)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(local_dir, dest)

    def pull(self, key: str, local_dir: Path) -> bool:
        src = self._path(key)
        if not src.is_dir():
            return False
        if local_dir.exists():
            shutil.rmtree(local_dir, ignore_errors=True)
        local_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, local_dir)
        return True


class StagingBackend:
    """Wrap any backend so the worker never touches the workspace.

    Per stage: pull the inputs it declares into a sandbox that mirrors the
    ``/work`` layout, run the inner backend against **the sandbox only**, then
    copy the produced out_dir back into the real workspace and publish it to the
    store for other machines.
    """

    _WANTS_STAGE_IO = True
    """Ask the Stage layer for this call's out_dir + input dirs.  Backends that
    don't set this are never passed the extra argument, so their signatures are
    untouched."""

    _STREAMING_SUPPORTED = False

    def __init__(self, inner: Any, store: ObjectStore,
                 keep_sandbox: bool = False) -> None:
        self.inner = inner
        self.store = store
        self.keep_sandbox = keep_sandbox
        # A remote inner scheduler still schedules remotely through the wrapper.
        self._REMOTE_SCHEDULING = bool(
            getattr(inner, "_REMOTE_SCHEDULING", False)
        )

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _workspace_mount(mounts: "dict[str, str]", workdir: str) -> "Optional[str]":
        for host, ctr in mounts.items():
            if ctr == workdir:
                return host
        return None

    def _stage_in(self, ws_host: Path, sandbox: Path,
                  inputs: "list[str]") -> None:
        for raw in inputs:
            src = Path(raw)
            try:
                rel = src.relative_to(ws_host)
            except ValueError:
                continue          # outside the workspace — mounted separately
            key = rel.as_posix()
            dest = sandbox / rel
            if self.store.pull(key, dest):
                continue          # another machine already published it
            if src.is_dir():      # first time out: seed the store from here
                shutil.copytree(src, dest, dirs_exist_ok=True)
                try:
                    self.store.push(dest, key)
                except OSError as exc:   # publishing is best-effort
                    log.warning(f"staging: could not publish {key}: {exc}")

    # -- contract --------------------------------------------------------
    def run(
        self,
        *,
        image: str,
        command: str,
        mounts: "dict[str, str]",
        cpu: int,
        ram_gb: float,
        workdir: str,
        gpu: bool = False,
        stage_io: "Optional[dict]" = None,
        **kw: Any,
    ) -> CommandResult:
        ws = self._workspace_mount(mounts, workdir)
        if ws is None or not stage_io:
            # Nothing to stage against — behave like the inner backend.
            return self.inner.run(
                image=image, command=command, mounts=mounts, cpu=cpu,
                ram_gb=ram_gb, workdir=workdir, gpu=gpu, **kw
            )

        ws_host = Path(ws)
        out_dir = Path(stage_io["out_dir"])
        sandbox = Path(tempfile.mkdtemp(prefix="bioflow-stage-"))
        try:
            self._stage_in(ws_host, sandbox, list(stage_io.get("inputs", [])))

            try:
                out_rel = out_dir.relative_to(ws_host)
            except ValueError:
                out_rel = Path(out_dir.name)
            (sandbox / out_rel).mkdir(parents=True, exist_ok=True)

            # The worker sees the sandbox as /work; external inputs keep their
            # own mounts so `/inputs/N` paths still resolve.
            staged_mounts = {
                h: c for h, c in mounts.items() if c != workdir
            }
            staged_mounts[str(sandbox)] = workdir

            result = self.inner.run(
                image=image, command=command, mounts=staged_mounts, cpu=cpu,
                ram_gb=ram_gb, workdir=workdir, gpu=gpu, **kw
            )

            # Bring the outputs home: the local out_dir is what downstream
            # stages and the cache sentinel read.
            produced = sandbox / out_rel
            if produced.is_dir():
                out_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(produced, out_dir, dirs_exist_ok=True)
                if result.exit_code == 0:
                    try:
                        self.store.push(produced, out_rel.as_posix())
                    except OSError as exc:
                        log.warning(f"staging: could not publish output: {exc}")
            return result
        finally:
            if not self.keep_sandbox:
                shutil.rmtree(sandbox, ignore_errors=True)
