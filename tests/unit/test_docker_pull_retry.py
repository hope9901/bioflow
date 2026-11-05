"""DockerBackend image pulls: retried, and registry errors surfaced.

Regression test for the 2026-11-04 nightly failure: a transient registry
error while pulling ``metabat2`` made the ``bin_genomes`` stage fail with
``404 ... No such image``.  docker-py's ``images.pull`` drops ``{"error": ...}``
messages from the pull stream, so the failure was misreported and never
retried.  The backend now pulls through the low-level API, retries with
backoff, and reports a pull that never succeeds as a pull failure.
"""
from __future__ import annotations

import pytest

docker_errors = pytest.importorskip("docker.errors")

from bioflow.core import runner
from bioflow.core.runner import DockerBackend


class _Container:
    def logs(self, **_):
        yield b"done\n"

    def wait(self, **_):
        return {"StatusCode": 0}

    def remove(self, **_):
        pass


class _Images:
    """``images.get`` raises ImageNotFound until the image has been pulled."""

    def __init__(self, present: bool) -> None:
        self.present = present

    def get(self, name):
        if not self.present:
            raise docker_errors.ImageNotFound(f"No such image: {name}")
        return name


class _API:
    """Low-level ``api.pull``: plays back one scripted stream per attempt."""

    def __init__(self, images: _Images, streams: list) -> None:
        self.images = images
        self.streams = list(streams)
        self.calls: list = []

    def pull(self, repo, tag=None, stream=False, decode=False):
        self.calls.append((repo, tag))
        msgs = self.streams.pop(0)
        if not any("error" in m for m in msgs):
            self.images.present = True
        return iter(msgs)


class _Containers:
    def __init__(self) -> None:
        self.ran = False

    def run(self, **_):
        self.ran = True
        return _Container()


def _backend(present: bool, streams: list):
    b = DockerBackend.__new__(DockerBackend)   # bypass docker.from_env()
    b.runtime = "docker"
    images = _Images(present)

    class _Client:
        pass

    client = _Client()
    client.images = images
    client.api = _API(images, streams)
    client.containers = _Containers()
    b.client = client
    return b


_OK = [{"status": "Pulling fs layer"}, {"status": "Download complete"}]
_TLS = [{"status": "Pulling fs layer"}, {"error": "net/http: TLS handshake timeout"}]


def _run(b):
    return b.run(image="quay.io/biocontainers/metabat2:2.18--h38e344b_2",
                 command="true", mounts={}, cpu=1, ram_gb=1, workdir="/work")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    sleeps: list = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    return sleeps


def test_present_image_is_not_pulled():
    b = _backend(present=True, streams=[])
    r = _run(b)
    assert r.exit_code == 0
    assert b.client.api.calls == []
    assert b.client.containers.ran


def test_transient_pull_error_is_retried(_no_sleep):
    b = _backend(present=False, streams=[_TLS, _TLS, _OK])
    r = _run(b)
    assert r.exit_code == 0, r.stderr
    assert len(b.client.api.calls) == 3
    assert b.client.api.calls[0] == ("quay.io/biocontainers/metabat2", "2.18--h38e344b_2")
    assert _no_sleep == [5, 15]
    assert b.client.containers.ran


def test_persistent_pull_error_is_reported_as_a_pull_failure():
    b = _backend(present=False, streams=[_TLS] * runner._PULL_ATTEMPTS)
    r = _run(b)
    assert r.exit_code == 1
    assert "could not pull image" in r.stderr
    assert "TLS handshake timeout" in r.stderr
    assert "No such image" not in r.stderr
    assert len(b.client.api.calls) == runner._PULL_ATTEMPTS
    assert not b.client.containers.ran


def test_digest_reference_pulls_by_digest():
    b = _backend(present=False, streams=[_OK])
    r = b.run(image="ghcr.io/hope9901/bioflow-scanpy@sha256:" + "a" * 64,
              command="true", mounts={}, cpu=1, ram_gb=1, workdir="/work")
    assert r.exit_code == 0, r.stderr
    assert b.client.api.calls == [("ghcr.io/hope9901/bioflow-scanpy", "sha256:" + "a" * 64)]
