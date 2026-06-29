"""Image-capability guard — every tool a stage invokes must exist in its image.

The smoke matrix only runs each recipe's *first* stage, so a stage that
shells out to a binary its container doesn't ship (the classic case:
``bwa | samtools sort`` in a bwa-only image that has no samtools) sails
through every test until someone actually runs that recipe.  This guard
closes that gap **statically + cheaply**:

1. For every registered recipe, render each stage's command string with
   mock arguments.
2. Extract the binaries the command invokes (the first token of every
   pipeline / ``&&`` / ``;`` / ``$(...)`` segment), minus shell builtins
   and coreutils.  Wrapper commands (``wine msconvert``) contribute the
   wrapper as a ``PATH`` tool **and** the wrapped Windows ``.exe`` as a
   separate must-exist binary.
3. Group the required binaries per image and assert — with one
   ``docker run <image> sh -c 'command -v …'`` per image — that every
   one is present (wrapped ``.exe`` files are located on disk instead,
   since they aren't on ``PATH``).  The image's own entrypoint is kept
   (not bypassed with ``--entrypoint sh``): some biocontainers activate
   a conda env on entry to set up ``PATH``, so probing past it would
   wrongly report tools missing.

No reference databases or fixtures are needed: it never runs the tools,
only checks they exist.  Marked ``docker`` + ``slow``; it pulls every
recipe image, so set ``BIOFLOW_PRUNE_IMAGES=1`` (the nightly job does) to
``docker rmi`` each image after its check and keep disk bounded.

Run locally::

    pytest tests/integration/test_image_capabilities.py -v -m docker
    # one image:
    pytest tests/integration/test_image_capabilities.py -v -m docker -k bwa
"""
from __future__ import annotations

import inspect
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

_docker_unavailable: str | None = None
try:
    import docker as _docker_mod  # type: ignore[import-not-found]

    _docker_mod.from_env().ping()
except Exception as exc:  # pragma: no cover - env dependent
    _docker_unavailable = str(exc)

pytestmark = [
    pytest.mark.docker,
    pytest.mark.slow,
    pytest.mark.skipif(
        _docker_unavailable is not None,
        reason=f"Docker not reachable: {_docker_unavailable}",
    ),
]


# ---------------------------------------------------------------------------
# Mock-render a stage's command, then extract the binaries it invokes.
# ---------------------------------------------------------------------------

class _Res:
    """Stand-in for a StageResult: has ``.out_dir``, is iterable, is a path."""

    out_dir = Path("/work/_mock")

    def __iter__(self):
        return iter((self,))

    def __str__(self):
        return "/work/_mock"

    __fspath__ = __str__


def _mock_args(func):
    """Build positional/keyword mock args for *func* from its signature.

    Recipe modules use ``from __future__ import annotations``, so every
    annotation is a string — we match on the text.
    """
    sig = inspect.signature(func)
    args, kwargs = [], {}
    for name, p in sig.parameters.items():
        if name == "out_dir":
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is not inspect.Parameter.empty:
            val = p.default
        else:
            ann = p.annotation if isinstance(p.annotation, str) else ""
            if "Path" in ann:
                val = Path(f"/work/{name}")
            elif ann == "str":
                val = name
            elif ann == "int":
                val = 1
            elif ann == "float":
                val = 1.0
            else:                       # unannotated → a StageResult
                val = _Res()
        if p.kind == p.KEYWORD_ONLY:
            kwargs[name] = val
        else:
            args.append(val)
    return args, kwargs


# Shell builtins / coreutils / common non-bio commands that every image
# is expected to have (or that aren't tools at all).  Anything left after
# this filter is treated as a bioinformatics binary that the image must
# ship.
_NON_TOOLS = {
    "bash", "sh", "for", "do", "done", "if", "then", "else", "elif", "fi",
    "while", "case", "esac", "[", "[[", "test", "true", "false", ":",
    "cp", "mv", "rm", "rmdir", "mkdir", "ls", "cat", "head", "tail", "echo",
    "printf", "cd", "pwd", "export", "set", "read", "unset", "eval", "exec",
    "zcat", "gzip", "gunzip", "bzip2", "tar", "awk", "gawk", "mawk", "sed",
    "grep", "egrep", "fgrep", "sort", "uniq", "wc", "cut", "tr", "paste",
    "basename", "dirname", "find", "xargs", "touch", "seq", "tee", "yes",
    "sleep", "env", "which", "command", "type", "ln", "chmod", "chown",
    "date", "wait", "kill", "head1", "mktemp", "cmp", "diff", "wget", "curl",
}

# Wrappers that exec another program: the real tool is the *next* word, run
# through the wrapper.  For these we check the wrapper is on PATH **and** that
# the wrapped Windows ``.exe`` actually ships in the image — otherwise a stage
# like ``wine msconvert`` would pass on ``command -v wine`` alone even if
# ``msconvert.exe`` were missing (the exact gap behind the 0.3.0-era pwiz bug).
_WRAPPERS = {"wine", "wine64", "wine64_anyuser"}

_WRAP_RE = re.compile(r"^\s*(?:bash|sh) -c '(.*)'\s*$", re.DOTALL)
# Shell keywords that introduce a command (so the word after them is one).
_KEYWORDS = r"\b(?:do|then|else|elif|fi|done|while|if|case|esac)\b"
_LEAD = re.compile(r"\s*([A-Za-z_][\w.\-/]*)")


def _extract_tools(cmd: str) -> "tuple[set[str], set[str]]":
    """Return ``(tools, wine_exes)`` the command invokes (best-effort parse).

    ``tools`` are binaries that must be on ``PATH``; ``wine_exes`` are the
    Windows executables launched through a :data:`_WRAPPERS` command (e.g.
    ``msconvert`` in ``wine msconvert``) — checked by locating ``<name>.exe``
    in the image rather than via ``command -v``.
    """
    # 1. Unwrap a leading ``bash -c '…'`` / ``sh -c '…'`` so the inner
    #    first command isn't swallowed.
    m = _WRAP_RE.match(cmd)
    if m:
        cmd = m.group(1)
    # 2. Drop quoted substrings (Rscript -e "…", awk programs, -R "@RG…")
    #    so their internal ``;`` / identifiers aren't read as commands.
    cmd = re.sub(r"'[^']*'", " ", cmd)
    cmd = re.sub(r'"[^"]*"', " ", cmd)
    # 3. ``for VAR in LIST`` — drop the loop variable + `in` so neither
    #    the var nor the list-of-paths is mistaken for a command.
    cmd = re.sub(r"\bfor\s+\w+\s+in\b", "\n", cmd)
    # 4. Turn every command separator and leading keyword into a newline,
    #    so the first token of each resulting segment is a command.
    cmd = re.sub(r"\|\||&&|[|&;`]|\$\(|\)|" + _KEYWORDS, "\n", cmd)

    tools: set[str] = set()
    wine_exes: set[str] = set()
    for seg in cmd.split("\n"):
        seg = seg.lstrip()
        mt = _LEAD.match(seg)
        if not mt:
            continue
        tok = mt.group(1)
        if seg[mt.end(1):mt.end(1) + 1] == "=":   # VAR=value assignment
            continue
        if tok.startswith("/"):
            continue
        if tok in _WRAPPERS:
            tools.add(tok)                        # the wrapper must be present
            for w in seg.split()[1:]:             # first real arg = wrapped exe
                if w.startswith("-") or "=" in w or w.startswith("/"):
                    continue
                wm = _LEAD.match(w)
                if wm:
                    wine_exes.add(wm.group(1))
                break
            continue
        if tok in _NON_TOOLS:
            continue
        tools.add(tok)
    return tools, wine_exes


def _collect() -> "tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], list[str]]":
    """Return (image→tools, image→wine_exes, image→sources, render-failures)."""
    from bioflow import recipes

    image_tools: dict[str, set[str]] = {}
    image_wine: dict[str, set[str]] = {}
    image_src: dict[str, set[str]] = {}
    failures: list[str] = []

    out_root = Path(tempfile.mkdtemp(prefix="imgcap_"))
    for rname in sorted(recipes.names()):
        pipe = recipes.get(rname)
        for stage in getattr(pipe, "stages", ()):
            image = getattr(stage, "image", None)
            if not image:
                continue
            try:
                args, kwargs = _mock_args(stage.func)
                out_dir = out_root / f"{rname}.{stage.name}"
                out_dir.mkdir(parents=True, exist_ok=True)
                cmd = stage.func(*args, out_dir=out_dir, **kwargs)
            except Exception as exc:  # pragma: no cover - signals a gap
                failures.append(f"{rname}.{stage.name}: {type(exc).__name__}: {exc}")
                continue
            if not isinstance(cmd, str):
                continue
            tools, wine_exes = _extract_tools(cmd)
            if tools or wine_exes:
                image_tools.setdefault(image, set()).update(tools)
                image_wine.setdefault(image, set()).update(wine_exes)
                image_src.setdefault(image, set()).add(f"{rname}.{stage.name}")
    return image_tools, image_wine, image_src, failures


_IMAGE_TOOLS, _IMAGE_WINE, _IMAGE_SRC, _RENDER_FAILURES = _collect()


def test_all_stage_commands_render():
    """Every stage's command must render with mock args (else we can't
    verify its image)."""
    assert not _RENDER_FAILURES, (
        "could not render these stage commands for the image-capability "
        "check:\n  " + "\n  ".join(_RENDER_FAILURES)
    )


def pytest_generate_tests(metafunc):
    if "image" in metafunc.fixturenames:
        images = sorted(set(_IMAGE_TOOLS) | set(_IMAGE_WINE))
        metafunc.parametrize("image", images, ids=[i.split("/")[-1] for i in images])


def test_image_provides_invoked_tools(image: str):
    """Assert *image* contains every binary the recipes invoke from it."""
    tools = sorted(_IMAGE_TOOLS.get(image, set()))
    wine_exes = sorted(_IMAGE_WINE.get(image, set()))
    checks = [
        f'command -v "{t}" >/dev/null 2>&1 || echo "MISSING:{t}"' for t in tools
    ]
    # Wrapped Windows tools (e.g. ``wine msconvert``) are not on PATH, so
    # ``command -v`` can't see them — confirm the ``<name>.exe`` actually
    # ships by locating it on disk, which avoids wine's slow/flaky startup.
    checks += [
        f'find / -iname "{e}.exe" 2>/dev/null | head -n1 | grep -q . '
        f'|| echo "MISSING:{e}.exe"'
        for e in wine_exes
    ]
    check = "; ".join(checks)
    try:
        # Mirror how the DockerBackend invokes a stage — ``sh -c`` as the
        # *command*, keeping the image's entrypoint (some biocontainers
        # use a conda-activation entrypoint that sets up PATH).  Probing
        # with ``--entrypoint sh`` would bypass that and wrongly report a
        # tool missing.
        proc = subprocess.run(
            ["docker", "run", "--rm", image, "sh", "-c", check],
            capture_output=True, text=True, timeout=1200,
        )
    finally:
        if os.environ.get("BIOFLOW_PRUNE_IMAGES"):
            subprocess.run(["docker", "rmi", "-f", image],
                           capture_output=True, text=True)

    if proc.returncode != 0 and "MISSING:" not in proc.stdout:
        pytest.fail(
            f"could not probe {image} (exit {proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout)[-500:]}"
        )
    missing = sorted(
        line.split("MISSING:", 1)[1].strip()
        for line in proc.stdout.splitlines() if line.startswith("MISSING:")
    )
    assert not missing, (
        f"{image} is missing tool(s) {missing} invoked by "
        f"{sorted(_IMAGE_SRC[image])}"
    )
