"""Docker container runner.

Execution model: the orchestrator process launches one container per pipeline
stage via the Docker SDK. When bioflow itself is inside a container, the
bind-mounted host Docker socket lets us spawn sibling containers (NOT
docker-in-docker). A shared /workspace volume is bind-mounted into every
stage container so artifacts flow between stages as files.

The backend is abstracted behind ContainerBackend so tests can use MockBackend
(records calls, touches declared output files) without a Docker daemon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from bioflow.core.checkpoint import load as _load_state, mark_completed
from bioflow.core.logger import get_logger
from bioflow.core.planner import ExecutionPlan, StagePlan
from bioflow.core.registry import Tool, load_registry


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
    ) -> CommandResult: ...


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
    ) -> CommandResult:
        self.calls.append(
            {
                "image": image,
                "command": command,
                "mounts": mounts,
                "cpu": cpu,
                "ram_gb": ram_gb,
                "workdir": workdir,
            }
        )
        for p in self._pending_outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
        self._pending_outputs = []
        return CommandResult(exit_code=0)


class DockerBackend:
    """Real Docker SDK backend (sibling-container pattern)."""

    def __init__(self) -> None:
        import docker  # type: ignore[import-not-found]

        self.client = docker.from_env()

    def run(
        self,
        *,
        image: str,
        command: str,
        mounts: dict[str, str],
        cpu: int,
        ram_gb: float,
        workdir: str,
    ) -> CommandResult:
        volumes = {h: {"bind": c, "mode": "rw"} for h, c in mounts.items()}
        try:
            container = self.client.containers.run(
                image=image,
                command=["sh", "-c", command],
                volumes=volumes,
                working_dir=workdir,
                mem_limit=f"{max(int(ram_gb), 1)}g",
                nano_cpus=int(cpu * 1_000_000_000),
                detach=True,
                remove=False,
            )
            result = container.wait()
            logs = container.logs().decode(errors="replace")
            container.remove(force=True)
            return CommandResult(
                exit_code=int(result.get("StatusCode", 1)),
                stdout=logs,
            )
        except Exception as e:  # docker.errors.APIError, ImageNotFound, etc.
            return CommandResult(exit_code=1, stderr=str(e))


def _render_command(
    tool: Tool, stage: StagePlan, plan: ExecutionPlan, stage_dir: Path
) -> str:
    """Minimal template substitution for MVP.

    Provides {out_dir}, {cpu}, {ram_gb}, plus every key in plan.inputs and
    stage.params. Unresolved placeholders are left verbatim — a richer planner
    will fill them in step 5+.
    """
    ctx: dict[str, object] = {
        "out_dir": str(stage_dir),
        "cpu": tool.resources.min.cpu,
        "ram_gb": int(tool.resources.min.ram_gb),
    }
    ctx.update(plan.inputs or {})
    ctx.update(stage.params or {})

    class _Safe(dict):
        def __missing__(self, key: str) -> str:  # type: ignore[override]
            return "{" + key + "}"

    return tool.command_template.format_map(_Safe(ctx)).strip()


def run_plan(
    plan: ExecutionPlan,
    *,
    backend: Optional[ContainerBackend] = None,
    registry_dir: Optional[Path] = None,
) -> None:
    """Execute every stage in plan.stages (declared order).

    - Looks up each stage's tool in the registry.
    - Renders the command template.
    - Invokes the container backend with a shared /workspace mount.
    - Persists a checkpoint after each successful stage so `bioflow run` can
      resume after a failure.
    """
    log = get_logger()
    backend = backend or DockerBackend()
    tools_by_id = {t.id: t for t in load_registry(registry_dir or plan.registry_dir)}
    workdir = Path(plan.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    state = _load_state(workdir)

    for stage in plan.stages:
        if stage.stage_id in state["completed_stages"]:
            log.info(f"SKIP {stage.stage_id} (checkpointed)")
            continue
        if stage.tool_id not in tools_by_id:
            raise ValueError(
                f"Tool '{stage.tool_id}' not found in registry "
                f"(stage {stage.stage_id})"
            )
        tool = tools_by_id[stage.tool_id]
        stage_dir = workdir / stage.stage_id.replace(".", "_")
        stage_dir.mkdir(parents=True, exist_ok=True)

        command = _render_command(tool, stage, plan, stage_dir)
        mounts = {str(workdir.resolve()): "/workspace"}

        log.info(
            f"RUN  {stage.stage_id}  tool={tool.id}  image={tool.container.image}"
        )
        result = backend.run(
            image=tool.container.image,
            command=command,
            mounts=mounts,
            cpu=tool.resources.min.cpu,
            ram_gb=tool.resources.min.ram_gb,
            workdir="/workspace",
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"Stage {stage.stage_id} failed (exit={result.exit_code}): "
                f"{result.stderr or result.stdout}"
            )
        mark_completed(workdir, stage.stage_id, {"stage_dir": str(stage_dir)})
        log.info(f"DONE {stage.stage_id}")
