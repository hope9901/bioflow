"""GPU passthrough + Podman-runtime support."""
from __future__ import annotations

import pytest

from bioflow import MockBackend, set_backend, set_workspace, stage
from bioflow.core import doctor


@pytest.fixture(autouse=True)
def _runtime(tmp_path):
    set_workspace(tmp_path / "ws")
    set_backend(MockBackend())
    yield


# ---------------------------------------------------------------------------
# @stage(gpu=...) threads through to the backend
# ---------------------------------------------------------------------------

class TestStageGpu:

    def test_stage_defaults_gpu_false(self):
        @stage(image="alpine:3", cache=False)
        def s(x, *, out_dir):
            return "true"
        assert s.gpu is False

    def test_stage_gpu_true_recorded_on_backend(self, tmp_path):
        backend = MockBackend()
        set_backend(backend)

        @stage(image="nvcr.io/tool:1", gpu=True, cache=False)
        def gpu_stage(x, *, out_dir):
            return f"run {x}"

        f = tmp_path / "in.dat"; f.write_text("x")
        gpu_stage(f)
        assert backend.calls, "stage did not run"
        assert backend.calls[0]["gpu"] is True

    def test_stage_cpu_only_passes_gpu_false(self, tmp_path):
        backend = MockBackend()
        set_backend(backend)

        @stage(image="alpine:3", cache=False)
        def cpu_stage(x, *, out_dir):
            return f"run {x}"

        f = tmp_path / "in.dat"; f.write_text("x")
        cpu_stage(f)
        assert backend.calls[0]["gpu"] is False


# ---------------------------------------------------------------------------
# run_plan passes tool.resources.gpu
# ---------------------------------------------------------------------------

class TestRunPlanGpu:

    def test_run_plan_forwards_tool_gpu(self, tmp_path, monkeypatch):
        from bioflow.core.planner import ExecutionPlan, StagePlan
        from bioflow.core.registry import Tool
        from bioflow.core.runner import run_plan

        tool = Tool.model_validate({
            "id": "gpu_tool", "name": "gpu_tool", "version": "1",
            "category": "single_cell", "stage": ["s1"],
            "applicable": {"species": ["any"], "read_type": ["short"], "mode": ["any"]},
            "container": {"image": "nvcr.io/x:1"},
            "resources": {
                "min": {"cpu": 2, "ram_gb": 4},
                "recommended": {"cpu": 4, "ram_gb": 8},
                "gpu": True,
            },
            "command_template": "echo {out_dir}",
        })
        monkeypatch.setattr("bioflow.core.runner.load_registry", lambda _d: [tool])

        plan = ExecutionPlan(
            pipeline="scrna_seq", species="any", read_type="short", mode="any",
            workdir=str(tmp_path), inputs={},
            stages=[StagePlan(stage_id="s1", tool_id="gpu_tool")],
        )
        backend = MockBackend()
        run_plan(plan, backend=backend, show_progress=False)
        assert backend.calls[0]["gpu"] is True


# ---------------------------------------------------------------------------
# DockerBackend GPU device requests + Podman host
# ---------------------------------------------------------------------------

class TestDockerBackendGpu:

    def test_gpu_device_request_added(self, monkeypatch):
        """gpu=True must attach a DeviceRequest to containers.run kwargs."""
        from bioflow.core.runner import DockerBackend

        captured: dict = {}

        class _FakeContainer:
            def logs(self, **_):  # noqa: D401
                return iter([b"done\n"])

            def wait(self, **_):
                return {"StatusCode": 0}

            def remove(self, **_):
                pass

        class _FakeContainers:
            def run(self, **kw):
                captured.update(kw)
                return _FakeContainer()

        class _FakeClient:
            containers = _FakeContainers()

        b = DockerBackend.__new__(DockerBackend)   # bypass __init__/docker
        b.client = _FakeClient()
        b.runtime = "docker"

        r = b.run(
            image="x:1", command="true", mounts={}, cpu=1, ram_gb=1,
            workdir="/work", gpu=True,
        )
        assert r.exit_code == 0
        assert "device_requests" in captured, "GPU run must set device_requests"

    def test_no_gpu_no_device_request(self, monkeypatch):
        from bioflow.core.runner import DockerBackend

        captured: dict = {}

        class _FakeContainer:
            def logs(self, **_):
                return iter([b""])

            def wait(self, **_):
                return {"StatusCode": 0}

            def remove(self, **_):
                pass

        class _FakeContainers:
            def run(self, **kw):
                captured.update(kw)
                return _FakeContainer()

        class _FakeClient:
            containers = _FakeContainers()

        b = DockerBackend.__new__(DockerBackend)
        b.client = _FakeClient()
        b.runtime = "docker"
        b.run(image="x:1", command="true", mounts={}, cpu=1, ram_gb=1,
              workdir="/work")
        assert "device_requests" not in captured


# ---------------------------------------------------------------------------
# doctor recognises podman
# ---------------------------------------------------------------------------

class TestDoctorPodman:

    def test_runtime_prefers_docker(self, monkeypatch):
        monkeypatch.setattr(
            doctor.shutil, "which",
            lambda n: f"/usr/bin/{n}" if n in ("docker", "podman") else None,
        )
        monkeypatch.delenv("BIOFLOW_CONTAINER_RUNTIME", raising=False)
        cli, path = doctor._container_runtime()
        assert cli == "docker"

    def test_runtime_falls_back_to_podman(self, monkeypatch):
        monkeypatch.setattr(
            doctor.shutil, "which",
            lambda n: "/usr/bin/podman" if n == "podman" else None,
        )
        monkeypatch.delenv("BIOFLOW_CONTAINER_RUNTIME", raising=False)
        cli, path = doctor._container_runtime()
        assert cli == "podman"

    def test_forced_runtime_env(self, monkeypatch):
        monkeypatch.setattr(
            doctor.shutil, "which",
            lambda n: f"/usr/bin/{n}" if n in ("docker", "podman") else None,
        )
        monkeypatch.setenv("BIOFLOW_CONTAINER_RUNTIME", "podman")
        cli, _ = doctor._container_runtime()
        assert cli == "podman"

    def test_docker_cli_check_reports_podman(self, monkeypatch):
        monkeypatch.setattr(
            doctor.shutil, "which",
            lambda n: "/usr/bin/podman" if n == "podman" else None,
        )
        monkeypatch.delenv("BIOFLOW_CONTAINER_RUNTIME", raising=False)
        r = doctor._check_docker_cli()
        assert r.status == "ok"
        assert "podman" in r.message
