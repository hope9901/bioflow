"""Staging for workers that can't see the workspace.

Docker/Apptainer/Slurm all bind-mount the workspace; a detached worker (cloud
batch, k8s without a shared volume) can't. StagingBackend wraps any of them,
shipping the content-addressed out_dirs out and back.

These cover the parts bioflow owns: the store round-trip, that the sandbox
mirrors the ``/work`` layout so the already-translated command still resolves,
that the workspace is *not* handed to the inner backend, and that outputs come
home. A real-container version of the same flow lives in
tests/integration/test_staging_real.py.
"""
from __future__ import annotations

from pathlib import Path

from bioflow.core.runner import CommandResult, MockBackend
from bioflow.core.staging import LocalDirStore, ObjectStore, StagingBackend


def test_local_dir_store_round_trip(tmp_path):
    store = LocalDirStore(tmp_path / "store")
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")

    assert store.exists("k1") is False
    store.push(src, "k1")
    assert store.exists("k1") is True

    dest = tmp_path / "dest"
    assert store.pull("k1", dest) is True
    assert (dest / "a.txt").read_text(encoding="utf-8") == "hello"
    assert store.pull("missing", tmp_path / "nope") is False


def test_local_dir_store_satisfies_the_protocol(tmp_path):
    assert isinstance(LocalDirStore(tmp_path), ObjectStore)


class RecordingBackend:
    """Inner backend that records what it was asked to mount, and writes an
    output file into the out_dir it was given (as a real tool would)."""

    def __init__(self, produce: str = "result.txt") -> None:
        self.calls: list[dict] = []
        self.produce = produce
        self.exit_code = 0

    def run(self, *, image, command, mounts, cpu, ram_gb, workdir,
            gpu=False, **kw) -> CommandResult:
        self.calls.append({"mounts": dict(mounts), "command": command})
        # Emulate the container writing into /work/<out_rel>.
        host_work = next(h for h, c in mounts.items() if c == workdir)
        out_rel = kw.get("_out_rel")
        target = Path(host_work)
        if out_rel:
            target = target / out_rel
        for p in Path(host_work).rglob("*"):
            if p.is_dir() and p.name.startswith("stageB__"):
                target = p
                break
        target.mkdir(parents=True, exist_ok=True)
        (target / self.produce).write_text("produced", encoding="utf-8")
        return CommandResult(exit_code=self.exit_code)


def _ws_with_upstream(tmp_path):
    ws = tmp_path / "ws"
    up = ws / ".cache" / "stageA__aaa111"
    up.mkdir(parents=True)
    (up / "up.txt").write_text("upstream data", encoding="utf-8")
    out = ws / ".cache" / "stageB__bbb222"
    out.mkdir(parents=True)
    return ws, up, out


def test_worker_never_gets_the_workspace(tmp_path):
    """The whole point: the inner backend must be handed a sandbox, not the
    workspace the submitter can see."""
    ws, up, out = _ws_with_upstream(tmp_path)
    inner = RecordingBackend()
    be = StagingBackend(inner, LocalDirStore(tmp_path / "store"))

    be.run(image="img:1", command="cat /work/.cache/stageA__aaa111/up.txt",
           mounts={str(ws): "/work"}, cpu=1, ram_gb=1, workdir="/work",
           stage_io={"out_dir": str(out), "inputs": [str(up)]})

    mounted = inner.calls[0]["mounts"]
    host_work = next(h for h, c in mounted.items() if c == "/work")
    assert Path(host_work) != ws, "workspace was handed straight to the worker"
    assert "bioflow-stage-" in host_work


def test_sandbox_mirrors_the_work_layout(tmp_path):
    """The command is already translated to /work/... paths, so the sandbox has
    to reproduce those exact relative paths for it to resolve."""
    ws, up, out = _ws_with_upstream(tmp_path)
    seen: dict = {}

    class Peek(RecordingBackend):
        def run(self, *, mounts, workdir, **kw):
            host = next(h for h, c in mounts.items() if c == workdir)
            seen["upstream"] = (Path(host) / ".cache" / "stageA__aaa111"
                                / "up.txt").read_text(encoding="utf-8")
            seen["outdir_exists"] = (Path(host) / ".cache"
                                     / "stageB__bbb222").is_dir()
            return super().run(mounts=mounts, workdir=workdir, **kw)

    inner = Peek()
    be = StagingBackend(inner, LocalDirStore(tmp_path / "store"))
    be.run(image="img:1", command="cat /work/.cache/stageA__aaa111/up.txt",
           mounts={str(ws): "/work"}, cpu=1, ram_gb=1, workdir="/work",
           stage_io={"out_dir": str(out), "inputs": [str(up)]})

    assert seen["upstream"] == "upstream data"   # input arrived at the right path
    assert seen["outdir_exists"] is True         # out_dir pre-created for the tool


def test_outputs_come_home_and_are_published(tmp_path):
    ws, up, out = _ws_with_upstream(tmp_path)
    store = LocalDirStore(tmp_path / "store")
    be = StagingBackend(RecordingBackend(), store)

    res = be.run(image="img:1", command="true", mounts={str(ws): "/work"},
                 cpu=1, ram_gb=1, workdir="/work",
                 stage_io={"out_dir": str(out), "inputs": [str(up)]})

    assert res.exit_code == 0
    assert (out / "result.txt").read_text(encoding="utf-8") == "produced"
    # published under its content-addressed key for other machines
    assert store.exists(".cache/stageB__bbb222")


def test_failed_stage_is_not_published(tmp_path):
    ws, up, out = _ws_with_upstream(tmp_path)
    store = LocalDirStore(tmp_path / "store")
    inner = RecordingBackend()
    inner.exit_code = 1
    be = StagingBackend(inner, store)

    res = be.run(image="img:1", command="false", mounts={str(ws): "/work"},
                 cpu=1, ram_gb=1, workdir="/work",
                 stage_io={"out_dir": str(out), "inputs": [str(up)]})

    assert res.exit_code == 1
    assert not store.exists(".cache/stageB__bbb222"), \
        "a failed stage must not be published as a reusable result"


def test_input_is_pulled_from_the_store_when_present(tmp_path):
    """Second machine: the upstream isn't local, it comes from the store."""
    ws, up, out = _ws_with_upstream(tmp_path)
    store = LocalDirStore(tmp_path / "store")
    store.push(up, ".cache/stageA__aaa111")

    import shutil
    shutil.rmtree(up)                      # gone locally — only the store has it

    seen: dict = {}

    class Peek(RecordingBackend):
        def run(self, *, mounts, workdir, **kw):
            host = next(h for h, c in mounts.items() if c == workdir)
            seen["text"] = (Path(host) / ".cache" / "stageA__aaa111"
                            / "up.txt").read_text(encoding="utf-8")
            return super().run(mounts=mounts, workdir=workdir, **kw)

    be = StagingBackend(Peek(), store)
    be.run(image="img:1", command="true", mounts={str(ws): "/work"},
           cpu=1, ram_gb=1, workdir="/work",
           stage_io={"out_dir": str(out), "inputs": [str(up)]})

    assert seen["text"] == "upstream data"


def test_without_stage_io_it_is_a_pass_through(tmp_path):
    """Backends are only handed stage_io when they ask; without it, don't
    silently change behaviour."""
    ws, _up, _out = _ws_with_upstream(tmp_path)
    inner = MockBackend()
    be = StagingBackend(inner, LocalDirStore(tmp_path / "store"))
    be.run(image="img:1", command="true", mounts={str(ws): "/work"},
           cpu=1, ram_gb=1, workdir="/work")
    assert inner.calls and inner.calls[0]["mounts"] == {str(ws): "/work"}


def test_stage_layer_only_passes_stage_io_when_asked():
    """Docker/Apptainer have fixed signatures — passing an extra kwarg would
    be a TypeError, so the Stage layer must gate on the opt-in flag."""
    from bioflow.core.runner import DockerBackend, SingularityBackend
    assert getattr(DockerBackend, "_WANTS_STAGE_IO", False) is False
    assert getattr(SingularityBackend, "_WANTS_STAGE_IO", False) is False
    assert StagingBackend._WANTS_STAGE_IO is True


def test_input_dirs_collected_from_args_and_fanout_lists(tmp_path):
    from bioflow.sdk._stage import _input_dirs

    class R:
        def __init__(self, p):
            self.out_dir = Path(p)

    dirs = _input_dirs(
        (R("/w/a"), [R("/w/b"), R("/w/c")], "not-a-result"),
        {"ref": R("/w/d"), "n": 3},
    )
    # str(Path(...)) so the expectation holds on POSIX and Windows alike
    assert dirs == [str(Path(p)) for p in ("/w/a", "/w/b", "/w/c", "/w/d")]


def test_input_dirs_dedupes():
    from bioflow.sdk._stage import _input_dirs

    class R:
        def __init__(self, p):
            self.out_dir = Path(p)

    assert _input_dirs((R("/w/a"), R("/w/a")), {}) == [str(Path("/w/a"))]
