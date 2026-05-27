"""End-to-end SDK ↔ real Docker integration tests.

The unit tests use MockBackend exclusively — these are the only
tests that prove the full ``@stage`` decorator path (path translation
+ workspace mount + image pull + command execution + log capture +
StageResult.ok) works against an actual Docker daemon.

Marked ``@pytest.mark.docker``; auto-skipped if Docker isn't reachable.
Run explicitly with::

    pytest tests/integration/test_sdk_real_docker.py -m docker -v

Image: ``alpine:3.19`` (~5 MB, BusyBox-style coreutils — keeps the
test fast and avoids hitting BioContainers from CI).  These tests
do not validate any specific BioContainer; they validate the SDK's
contract with Docker.

If these fail, the multi-cadence freshness model is moot — none of
the recipes will work in real life either.
"""
from __future__ import annotations

from pathlib import Path

import pytest


# Skip the whole module if Docker isn't reachable
_docker_unavailable: str | None = None
try:
    import docker as _docker_mod   # type: ignore[import-not-found]
    _client = _docker_mod.from_env()
    _client.ping()
except Exception as exc:
    _docker_unavailable = str(exc)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        _docker_unavailable is not None,
        reason=f"Docker not reachable: {_docker_unavailable}",
    ),
]


@pytest.fixture(autouse=True)
def _runtime(tmp_path):
    from bioflow import set_workspace, set_backend, DockerBackend
    set_workspace(tmp_path / "ws")
    set_backend(DockerBackend())
    yield


class TestSdkRoundtrip:
    """The minimum viable proof that @stage works with real Docker."""

    def test_single_stage_echo(self, tmp_path):
        """One stage → one container → stdout captured → exit 0."""
        from bioflow import stage
        @stage(image="alpine:3.19", cpu=1, ram_gb=1, cache=False)
        def echo(msg: str, *, out_dir):
            return f"sh -c 'echo {msg} > {out_dir}/out.txt'"

        result = echo("hello-bioflow")
        assert result.ok, f"stage failed: stderr={result.stderr[:200]}"
        assert (Path(result.out_dir) / "out.txt").read_text().strip() == "hello-bioflow"

    def test_two_stage_chain(self, tmp_path):
        """Stage 2 reads Stage 1's output through the workspace mount."""
        from bioflow import stage

        @stage(image="alpine:3.19", cpu=1, ram_gb=1, cache=False)
        def gen(*, out_dir):
            return f"sh -c 'printf line1\\\\nline2\\\\nline3\\\\n > {out_dir}/data.txt'"

        @stage(image="alpine:3.19", cpu=1, ram_gb=1, cache=False, depends_on=gen)
        def count(src, *, out_dir):
            return f"sh -c 'wc -l {src.out_dir}/data.txt > {out_dir}/count.txt'"

        a = gen()
        assert a.ok
        b = count(a)
        assert b.ok
        # `wc -l` output is "3 /work/.../data.txt"
        cnt_line = (Path(b.out_dir) / "count.txt").read_text().strip()
        assert cnt_line.split()[0] == "3"

    def test_failure_propagates(self, tmp_path):
        """A non-zero exit code is reported via StageResult, not raised."""
        from bioflow import stage
        @stage(image="alpine:3.19", cpu=1, ram_gb=1, cache=False)
        def fail(*, out_dir):
            return "sh -c 'exit 42'"

        result = fail()
        assert not result.ok
        assert result.exit_code == 42

    def test_external_input_mounted(self, tmp_path):
        """A Path argument outside the workspace must be auto-mounted +
        translated — this is the BLOCKER 2 fix verified against real Docker."""
        from bioflow import stage

        external = tmp_path.parent / "_outside_ws_input.txt"
        external.write_text("EXTERNAL\n", encoding="utf-8")

        @stage(image="alpine:3.19", cpu=1, ram_gb=1, cache=False)
        def read_it(p: Path, *, out_dir):
            return f"sh -c 'cat {p} > {out_dir}/echo.txt'"

        try:
            result = read_it(external)
            assert result.ok, f"stderr: {result.stderr[:300]}"
            got = (Path(result.out_dir) / "echo.txt").read_text().strip()
            assert got == "EXTERNAL"
        finally:
            external.unlink(missing_ok=True)


class TestCaching:
    """Cache must survive across calls when inputs are unchanged."""

    def test_second_call_is_cache_hit(self, tmp_path):
        from bioflow import stage

        @stage(image="alpine:3.19", cpu=1, ram_gb=1, cache=True)
        def slow(seed: int, *, out_dir):
            return f"sh -c 'echo {seed} > {out_dir}/seed.txt'"

        a = slow(42)
        b = slow(42)
        assert a.ok and b.ok
        assert b.cached, "Second identical call should be a cache hit"
        # Both reference the same out_dir
        assert a.out_dir == b.out_dir
