"""DockerBackend stage-timeout watchdog.

Regression test for the bug found during the bug-hunt: the log-streaming
loop blocks until the container exits, so ``container.wait(timeout=…)``
(a docker-py HTTP timeout) could never bound a runaway container.  The
watchdog timer must actually kill it and report exit 124.
"""
from __future__ import annotations

import threading

from bioflow.core.runner import DockerBackend


class _BlockingContainer:
    """Fake container whose log stream blocks until ``kill()`` is called."""

    def __init__(self) -> None:
        self._unblock = threading.Event()
        self.killed = False

    def logs(self, **_):
        # Yield one line, then block until kill() releases us — emulating a
        # container that keeps running past the timeout.
        yield b"working...\n"
        self._unblock.wait(timeout=10)

    def kill(self):
        self.killed = True
        self._unblock.set()

    def wait(self, **_):
        return {"StatusCode": 137}   # 128 + SIGKILL(9)

    def remove(self, **_):
        pass


class _FastContainer:
    """Fake container that finishes immediately (no timeout)."""

    def logs(self, **_):
        yield b"done\n"

    def wait(self, **_):
        return {"StatusCode": 0}

    def remove(self, **_):
        pass


def _backend_with(container):
    b = DockerBackend.__new__(DockerBackend)   # bypass docker.from_env()
    b.runtime = "docker"

    class _Containers:
        def run(self, **_):
            return container

    class _Client:
        containers = _Containers()

    b.client = _Client()
    return b


def test_timeout_kills_runaway_container(monkeypatch):
    # Don't let the real clamp touch nano_cpus math; cpu_count is fine.
    container = _BlockingContainer()
    b = _backend_with(container)
    r = b.run(
        image="x:1", command="sleep 999", mounts={}, cpu=1, ram_gb=1,
        workdir="/work", timeout=1,
    )
    assert container.killed, "watchdog did not kill the container"
    assert r.exit_code == 124, f"expected timeout exit 124, got {r.exit_code}"
    assert "timeout" in (r.stderr or "").lower()


def test_no_timeout_completes_normally():
    b = _backend_with(_FastContainer())
    r = b.run(
        image="x:1", command="true", mounts={}, cpu=1, ram_gb=1,
        workdir="/work",   # timeout=None
    )
    assert r.exit_code == 0
    assert "done" in r.stdout


def test_fast_container_with_generous_timeout_not_killed():
    container = _FastContainer()
    b = _backend_with(container)
    r = b.run(
        image="x:1", command="true", mounts={}, cpu=1, ram_gb=1,
        workdir="/work", timeout=30,
    )
    assert r.exit_code == 0   # finished well within the timeout


class _ChattyContainer:
    """Fake container that emits far more lines than the retention cap."""

    def __init__(self, n: int) -> None:
        self.n = n

    def logs(self, **_):
        for i in range(self.n):
            yield f"line {i}\n".encode()

    def wait(self, **_):
        return {"StatusCode": 0}

    def remove(self, **_):
        pass


def test_stdout_is_capped_to_tail():
    """A tool emitting millions of lines must not be kept in full."""
    from bioflow.core.runner import _STDOUT_TAIL_LINES

    n = _STDOUT_TAIL_LINES + 1000
    b = _backend_with(_ChattyContainer(n))
    r = b.run(image="x:1", command="noisy", mounts={}, cpu=1, ram_gb=1,
              workdir="/work")
    assert r.exit_code == 0
    lines = r.stdout.splitlines()
    assert len(lines) == _STDOUT_TAIL_LINES, "stdout not capped to the tail"
    # It kept the *tail*, not the head.
    assert lines[-1] == f"line {n - 1}"
    assert lines[0] == f"line {n - _STDOUT_TAIL_LINES}"
