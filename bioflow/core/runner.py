"""Docker container runner.

Execution model: the orchestrator process launches one container per pipeline
stage via the Docker SDK. When bioflow itself is inside a container, the
bind-mounted host Docker socket lets us spawn sibling containers (NOT
docker-in-docker). A shared /workspace volume is bind-mounted into every
stage container so artifacts flow between stages as files.

The backend is abstracted behind ContainerBackend so tests can use MockBackend
(records calls, touches declared output files) without a Docker daemon.

Progress display
----------------
``run_plan`` uses a Rich progress bar when *rich* is installed (it is listed as
a dependency).  Each active stage is shown with a spinner, tool name, and
elapsed time.  Pass ``show_progress=False`` to suppress it.

Log streaming
-------------
``DockerBackend`` streams container stdout/stderr in real time via
``container.logs(stream=True)``.  The decoded lines are passed to an optional
``log_callback`` so the caller can display or buffer them.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from rich.progress import TaskID

from bioflow.core.checkpoint import (
    load as _load_state,
    mark_completed,
    mark_failed,
)
from bioflow.core.logger import get_logger
from bioflow.core.planner import ExecutionPlan, StagePlan
from bioflow.core.registry import Tool, load_registry

log = get_logger()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CommandResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


@runtime_checkable
class ContainerBackend(Protocol):
    def run(
        self,
        *,
        image: str,
        command: str,
        mounts: dict[str, str],
        cpu: int,
        ram_gb: float,
        workdir: str,
        gpu: bool = False,
    ) -> CommandResult: ...


# ---------------------------------------------------------------------------
# Mock backend (tests)
# ---------------------------------------------------------------------------

class MockBackend:
    """Records calls and touches declared output files. Used in unit tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._pending_outputs: list[Path] = []

    def will_produce(self, paths: list[Path]) -> None:
        """Register files the NEXT run() call should touch into existence."""
        self._pending_outputs = [Path(p) for p in paths]

    def run(
        self,
        *,
        image: str,
        command: str,
        mounts: dict[str, str],
        cpu: int,
        ram_gb: float,
        workdir: str,
        gpu: bool = False,
        **_ignored,
    ) -> CommandResult:
        self.calls.append(
            {
                "image": image,
                "command": command,
                "mounts": mounts,
                "cpu": cpu,
                "ram_gb": ram_gb,
                "workdir": workdir,
                "gpu": gpu,
            }
        )
        for p in self._pending_outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        self._pending_outputs = []
        return CommandResult(exit_code=0)


# How many trailing stdout lines a stage retains in memory for error
# reporting.  Live output still streams in full to log_callback; only the
# in-memory copy returned in CommandResult is capped, so a tool that emits
# millions of lines can't OOM the orchestrator.
_STDOUT_TAIL_LINES = 5000


def _clamp_resources(cpu: int, ram_gb: float) -> "tuple[int, float]":
    """Clamp a stage's requested CPU / RAM to the host's capacity.

    Docker refuses to create a container whose ``--cpus`` exceeds the host
    core count, so a stage declaring ``cpu=8`` must not be sent verbatim to
    a 4-core host — it would fail to start.  Memory is clamped too (a
    ``mem_limit`` above host RAM is meaningless and risks an instant OOM).
    Both floor at 1 so a container is always launchable.
    """
    host_cpu = os.cpu_count() or 1
    eff_cpu = max(1, min(int(cpu), host_cpu))

    eff_ram = ram_gb
    try:
        import psutil  # noqa: PLC0415

        host_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        # Leave a little headroom for the host/OS.
        eff_ram = max(1.0, min(float(ram_gb), host_ram_gb * 0.9))
    except Exception:
        eff_ram = max(1.0, float(ram_gb))
    return eff_cpu, eff_ram


# ---------------------------------------------------------------------------
# Docker backend (production)
# ---------------------------------------------------------------------------

class DockerBackend:
    """Real Docker SDK backend (sibling-container pattern).

    Streams container stdout/stderr in real time via
    ``container.logs(stream=True, follow=True)`` and surfaces them through
    an optional ``log_callback`` so callers can display or buffer them.

    Container runtime
    -----------------
    Works with **Podman** as well as Docker: Podman ships a
    Docker-compatible API socket, so pointing ``DOCKER_HOST`` (or the
    bioflow-specific ``BIOFLOW_DOCKER_HOST``) at the Podman socket — e.g.
    ``unix:///run/user/1000/podman/podman.sock`` — routes every sibling
    container through Podman with no other change.  ``base_url`` overrides
    both.

    GPU
    ---
    When ``run(..., gpu=True)`` the backend attaches all host GPUs via a
    Docker ``DeviceRequest`` (the API equivalent of ``--gpus all``).  The
    host needs the NVIDIA Container Toolkit; on a CPU-only host the
    request is dropped with a warning rather than failing the run.
    """

    _STREAMING_SUPPORTED = True    # sentinel for run_plan

    def __init__(self, base_url: Optional[str] = None) -> None:
        import docker  # type: ignore[import-not-found]

        url = (
            base_url
            or os.environ.get("BIOFLOW_DOCKER_HOST")
            or os.environ.get("DOCKER_HOST")
        )
        if url:
            self.client = docker.DockerClient(base_url=url)  # type: ignore[attr-defined]
        else:
            self.client = docker.from_env()  # type: ignore[attr-defined]
        self.runtime = os.environ.get("BIOFLOW_CONTAINER_RUNTIME", "docker")

    def _gpu_device_requests(self):
        """Return device_requests for all GPUs, or None if unavailable."""
        try:
            import docker  # type: ignore[import-not-found]
            return [docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])]
        except Exception as exc:
            log.warning(f"GPU requested but device request could not be built: {exc}")
            return None

    def run(
        self,
        *,
        image: str,
        command: str,
        mounts: dict[str, str],
        cpu: int,
        ram_gb: float,
        workdir: str,
        gpu: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: Optional[int] = None,   # seconds; None = no limit
    ) -> CommandResult:
        volumes = {h: {"bind": c, "mode": "rw"} for h, c in mounts.items()}
        extra: dict = {}
        if gpu:
            dr = self._gpu_device_requests()
            if dr is not None:
                extra["device_requests"] = dr

        # Clamp the requested CPU/RAM to what the host actually has.  Docker
        # *rejects* a container whose --cpus exceeds the host core count
        # ("range of CPUs is from 0.01 to N.00"), so a stage declaring
        # cpu=8 would fail to even start on a 4-core CI runner or a small
        # workstation.  A request larger than the host should degrade to
        # "use everything available", not crash.
        eff_cpu, eff_ram = _clamp_resources(cpu, ram_gb)

        container = None
        timer = None
        timed_out = {"flag": False}
        try:
            container = self.client.containers.run(
                image=image,
                command=["sh", "-c", command],
                volumes=volumes,
                working_dir=workdir,
                mem_limit=f"{max(math.ceil(eff_ram), 1)}g",
                nano_cpus=int(eff_cpu * 1_000_000_000),
                detach=True,
                remove=False,
                **extra,
            )

            # Enforce stage_timeout with a watchdog.  The log-streaming loop
            # below blocks until the container exits, so ``container.wait
            # (timeout=…)`` (a docker-py HTTP read timeout, not a runtime
            # cap) can never fire for a runaway container — a timer that
            # kills the container is the only thing that actually bounds
            # the runtime.
            if timeout is not None and timeout > 0:
                import threading  # noqa: PLC0415

                def _kill() -> None:
                    timed_out["flag"] = True
                    try:
                        container.kill()
                    except Exception:
                        pass

                timer = threading.Timer(timeout, _kill)
                timer.daemon = True
                timer.start()

            # Retain only the tail in memory: the returned stdout is used
            # for error diagnosis, not as the artifact (tools write their
            # real output to files in the workspace).  A chatty tool
            # (Roary, IQ-TREE) can emit millions of lines, which would
            # OOM the orchestrator if kept in full.  Every line is still
            # streamed live to log_callback.
            from collections import deque  # noqa: PLC0415

            stdout_lines: "deque[str]" = deque(maxlen=_STDOUT_TAIL_LINES)
            for chunk in container.logs(stream=True, follow=True):
                line = chunk.decode(errors="replace").rstrip("\n")
                stdout_lines.append(line)
                if log_callback:
                    log_callback(line)

            result = container.wait()
            if timer is not None:
                timer.cancel()
            container.remove(force=True)

            if timed_out["flag"]:
                return CommandResult(
                    exit_code=124,   # conventional timeout exit code
                    stdout="\n".join(stdout_lines),
                    stderr=f"stage exceeded timeout of {timeout}s and was killed",
                )
            return CommandResult(
                exit_code=int(result.get("StatusCode", 1)),
                stdout="\n".join(stdout_lines),
            )
        except Exception as exc:
            if timer is not None:
                timer.cancel()
            # On any error the container may still be running — remove it.
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            return CommandResult(exit_code=1, stderr=str(exc))


# ---------------------------------------------------------------------------
# Singularity / Apptainer backend (HPC — no Docker daemon)
# ---------------------------------------------------------------------------

def _apptainer_bin() -> str:
    """Resolve the container CLI: ``BIOFLOW_APPTAINER_BIN``, then apptainer,
    then singularity (apptainer is the renamed successor)."""
    import shutil  # noqa: PLC0415

    override = os.environ.get("BIOFLOW_APPTAINER_BIN")
    if override:
        return override
    for cand in ("apptainer", "singularity"):
        if shutil.which(cand):
            return cand
    # Fall back to "apptainer"; the missing-binary error surfaces at run().
    return "apptainer"


class SingularityBackend:
    """Run each stage through Apptainer/Singularity instead of Docker.

    Most HPC clusters forbid the Docker daemon but ship Apptainer
    (formerly Singularity).  BioContainers images are pullable directly
    over the Docker transport, so each stage runs as::

        apptainer exec [--nv] --cleanenv --bind <host>:<ctr> --pwd <workdir> \\
            docker://<image> sh -c '<command>'

    The image is pulled + converted to a SIF on first use and cached by
    Apptainer (``APPTAINER_CACHEDIR``); later stages reuse it.  ``--cleanenv``
    keeps the host environment out of the container, matching Docker's
    isolation.

    Resources
    ---------
    Unlike Docker, Apptainer does not itself cap CPU/RAM — on a cluster that
    is the job scheduler's responsibility (e.g. the Slurm allocation).
    ``cpu`` / ``ram_gb`` are accepted but not enforced here; a future
    SlurmBackend will translate them into ``sbatch`` directives.
    """

    _STREAMING_SUPPORTED = True

    def __init__(self, binary: Optional[str] = None) -> None:
        self.binary = binary or _apptainer_bin()

    def _build_argv(
        self, *, image: str, command: str, mounts: dict[str, str],
        workdir: str, gpu: bool,
    ) -> "list[str]":
        argv = [self.binary, "exec", "--cleanenv"]
        if gpu:
            argv.append("--nv")
        for host, ctr in mounts.items():
            argv += ["--bind", f"{host}:{ctr}"]
        if workdir:
            argv += ["--pwd", workdir]
        # A bare registry ref (quay.io/biocontainers/…) needs the docker
        # transport; a SIF path or oras://… ref is used as-is.
        ref = image if "://" in image else f"docker://{image}"
        argv += [ref, "sh", "-c", command]
        return argv

    def run(
        self,
        *,
        image: str,
        command: str,
        mounts: dict[str, str],
        cpu: int,
        ram_gb: float,
        workdir: str,
        gpu: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: Optional[int] = None,
    ) -> CommandResult:
        import subprocess  # noqa: PLC0415
        from collections import deque  # noqa: PLC0415

        argv = self._build_argv(
            image=image, command=command, mounts=mounts,
            workdir=workdir, gpu=gpu,
        )
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            return CommandResult(
                exit_code=127,
                stderr=(
                    f"'{self.binary}' not found — install Apptainer/Singularity "
                    "or set BIOFLOW_APPTAINER_BIN (HPC backend)."
                ),
            )

        timed_out = {"flag": False}
        timer = None
        if timeout is not None and timeout > 0:
            import threading  # noqa: PLC0415

            def _kill() -> None:
                timed_out["flag"] = True
                try:
                    proc.kill()
                except Exception:
                    pass

            timer = threading.Timer(timeout, _kill)
            timer.daemon = True
            timer.start()

        # Retain only the tail in memory (the real artifacts are files in the
        # workspace); every line still streams live to log_callback.
        stdout_lines: "deque[str]" = deque(maxlen=_STDOUT_TAIL_LINES)
        if proc.stdout is not None:
            for line in proc.stdout:
                line = line.rstrip("\n")
                stdout_lines.append(line)
                if log_callback:
                    log_callback(line)
        proc.wait()
        if timer is not None:
            timer.cancel()

        if timed_out["flag"]:
            return CommandResult(
                exit_code=124,   # conventional timeout exit code
                stdout="\n".join(stdout_lines),
                stderr=f"stage exceeded timeout of {timeout}s and was killed",
            )
        return CommandResult(
            exit_code=int(proc.returncode or 0),
            stdout="\n".join(stdout_lines),
        )


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def make_backend(name: Optional[str] = None) -> ContainerBackend:
    """Construct the container backend selected by *name* or ``BIOFLOW_BACKEND``.

    - ``docker`` (default) / ``podman`` → :class:`DockerBackend` (Podman speaks
      the Docker API; point ``BIOFLOW_DOCKER_HOST`` at its socket).
    - ``singularity`` / ``apptainer`` → :class:`SingularityBackend` (HPC, no
      daemon, no ``docker`` Python package needed).
    """
    name = (name or os.environ.get("BIOFLOW_BACKEND") or "docker").lower().strip()
    if name in ("singularity", "apptainer"):
        return SingularityBackend()
    if name in ("docker", "podman", ""):
        return DockerBackend()
    raise ValueError(
        f"Unknown BIOFLOW_BACKEND '{name}' — expected one of: "
        "docker, podman, singularity, apptainer."
    )


# ---------------------------------------------------------------------------
# Rich progress context
# ---------------------------------------------------------------------------

class _NoOpProgress:
    """Fallback when Rich is not available or progress is suppressed."""
    def __enter__(self) -> "_NoOpProgress":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def update_stage(self, stage_id: str, tool_id: str) -> None:
        pass

    def mark_done(self, failed: bool = False) -> None:
        pass


class _RichProgress:
    """Thin wrapper around ``rich.progress.Progress`` for pipeline stages."""

    def __init__(self, total: int) -> None:
        from rich.progress import (  # noqa: PLC0415
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )
        self._prog = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description:<50}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
        )
        self._total = total
        self._task_id: Optional["TaskID"] = None

    def __enter__(self) -> "_RichProgress":
        self._prog.__enter__()
        self._task_id = self._prog.add_task("Initialising…", total=self._total)
        return self

    def __exit__(self, *args) -> None:
        self._prog.__exit__(*args)

    def update_stage(self, stage_id: str, tool_id: str) -> None:
        if self._task_id is None:
            return
        self._prog.update(
            self._task_id,
            description=f"[{stage_id}]  {tool_id}",
        )

    def mark_done(self, failed: bool = False) -> None:
        if self._task_id is None:
            return
        if failed:
            self._prog.update(self._task_id, description="[red]FAILED")
        else:
            self._prog.advance(self._task_id)


def _progress_ctx(total: int, show: bool) -> "_NoOpProgress | _RichProgress":
    if not show or total == 0:
        return _NoOpProgress()
    try:
        return _RichProgress(total)
    except ImportError:
        return _NoOpProgress()


# ---------------------------------------------------------------------------
# Command template rendering
# ---------------------------------------------------------------------------

def _render_command(
    tool: Tool, stage: StagePlan, plan: ExecutionPlan, stage_dir: Path
) -> str:
    """Minimal template substitution for MVP.

    Provides {out_dir}, {cpu}, {ram_gb}, plus every key in plan.inputs and
    stage.params.  Unresolved placeholders are left verbatim.
    """
    ctx: dict[str, object] = {
        "out_dir": str(stage_dir),
        "cpu": tool.resources.min.cpu,
        "ram_gb": int(tool.resources.min.ram_gb),
    }
    ctx.update(plan.inputs or {})
    ctx.update(stage.params or {})

    _unresolved: list[str] = []

    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            _unresolved.append(key)
            return "{" + key + "}"

    rendered = tool.command_template.format_map(_Safe(ctx)).strip()
    if _unresolved:
        log.warning(
            f"[{stage.stage_id}] Command template has unresolved placeholder(s): "
            + ", ".join(f"{{{k}}}" for k in _unresolved)
            + " — the container will receive the literal placeholder text. "
            "Check that all required inputs are provided in the config."
        )
    return rendered


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_plan(
    plan: ExecutionPlan,
    *,
    backend: Optional[ContainerBackend] = None,
    registry_dir: Optional[Path] = None,
    show_progress: bool = True,
    stage_timeout: Optional[int] = None,   # seconds per stage; None = no limit
) -> None:
    """Execute every stage in plan.stages in declared order.

    Features
    --------
    * Loads checkpoint — already-completed stages are skipped automatically.
    * Rich progress bar shows stage/tool/elapsed time (suppressed when
      ``show_progress=False`` or rich is not installed).
    * ``DockerBackend`` streams container logs via logger.debug in real time.
    * On failure, records the error in the checkpoint (``mark_failed``) so
      ``report.py`` can highlight it in the HTML summary.
    """
    backend = backend or make_backend()
    tools_by_id = {t.id: t for t in load_registry(registry_dir or plan.registry_dir)}
    workdir = Path(plan.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    state = _load_state(workdir)

    active = [
        s for s in plan.stages
        if s.stage_id not in state.get("completed_stages", [])
    ]

    # Decide whether backend supports streaming log_callback
    supports_streaming = getattr(backend, "_STREAMING_SUPPORTED", False)

    with _progress_ctx(len(active), show_progress) as prog:
        for stage in plan.stages:
            if stage.stage_id in state.get("completed_stages", []):
                log.info(f"SKIP {stage.stage_id} (checkpointed)")
                continue

            if stage.tool_id not in tools_by_id:
                err = (
                    f"Tool '{stage.tool_id}' not found in registry "
                    f"(stage {stage.stage_id})"
                )
                mark_failed(workdir, stage.stage_id, err)
                prog.mark_done(failed=True)
                raise ValueError(err)

            tool = tools_by_id[stage.tool_id]
            stage_dir = workdir / stage.stage_id.replace(".", "_")
            stage_dir.mkdir(parents=True, exist_ok=True)

            command = _render_command(tool, stage, plan, stage_dir)
            mounts = {str(workdir.resolve()): "/workspace"}

            image_ref = tool.container.pinned_image
            log.info(
                f"RUN  {stage.stage_id}  tool={tool.id}  image={image_ref}"
                + ("" if tool.container.image_digest else "  [unpinned]")
            )
            prog.update_stage(stage.stage_id, tool.id)

            # Build kwargs — only pass log_callback if backend supports it
            run_kwargs: dict = dict(
                image=image_ref,
                command=command,
                mounts=mounts,
                cpu=tool.resources.min.cpu,
                ram_gb=tool.resources.min.ram_gb,
                workdir="/workspace",
                gpu=bool(tool.resources.gpu),
            )
            if supports_streaming:
                run_kwargs["log_callback"] = lambda line: log.debug(
                    f"  [{stage.stage_id}] {line}"
                )
                if stage_timeout is not None:
                    run_kwargs["timeout"] = stage_timeout

            try:
                result = backend.run(**run_kwargs)
            except Exception as exc:
                mark_failed(workdir, stage.stage_id, str(exc))
                prog.mark_done(failed=True)
                raise RuntimeError(
                    f"Stage {stage.stage_id} errored unexpectedly: {exc}"
                ) from exc

            if result.exit_code != 0:
                err_msg = (result.stderr or result.stdout or "")[:1000]
                mark_failed(
                    workdir, stage.stage_id,
                    f"exit_code={result.exit_code}",
                    result.stderr or result.stdout,
                )
                prog.mark_done(failed=True)
                raise RuntimeError(
                    f"Stage {stage.stage_id} failed "
                    f"(exit={result.exit_code}): {err_msg}"
                )

            mark_completed(workdir, stage.stage_id, {"stage_dir": str(stage_dir)})
            log.info(f"DONE {stage.stage_id}")
            prog.mark_done()
