"""Host ↔ container path translation + external-input bind mounting.

Two responsibilities:

* :func:`_to_container_path` / :func:`_translate_command` — convert
  host paths *inside the active workspace* to their ``/work``-relative
  container form.
* :func:`_collect_external_mounts` / :func:`_apply_external_translation`
  — for ``Path`` arguments living *outside* the workspace, allocate
  additional bind mounts at ``/inputs/<n>`` and rewrite the command
  string.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any


_CONTAINER_WORKSPACE = PurePosixPath("/work")
_CONTAINER_INPUTS = PurePosixPath("/inputs")

# Characters in an external input's *basename* that would break the
# unquoted token the recipe builds into its shell command.  (The parent
# directory is safe — it is replaced by the space-free /inputs/<n>.)
_SHELL_UNSAFE_CHARS = set(" \t\n'\"\\;&|<>()$`*?{}[]")


def _reject_unsafe_basename(path: Path) -> None:
    """Raise if *path*'s basename contains a shell-unsafe character.

    bioflow mounts an external file's parent at /inputs/<n> and splices
    the basename into the recipe's command unquoted.  A space or shell
    metacharacter there silently corrupts the command, so we surface a
    clear error and tell the user to rename / symlink to a safe name.
    """
    bad = sorted({c for c in path.name if c in _SHELL_UNSAFE_CHARS})
    if bad:
        shown = ", ".join(repr(c) for c in bad)
        raise ValueError(
            f"Input file name {path.name!r} contains shell-unsafe "
            f"character(s) {shown}. bioflow splices external input names "
            f"into container commands unquoted, so they must avoid spaces "
            f"and shell metacharacters. Rename (or symlink) the file to a "
            f"name without those characters and re-run. (The containing "
            f"directory may contain spaces — only the file name matters.)"
        )


def _to_container_path(host_path: Path, workspace: Path) -> str:
    """Translate a host path inside the workspace to its /work-relative
    container path.  Raises if the host path is outside the workspace."""
    host_resolved = Path(host_path).resolve()
    try:
        rel = host_resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"Path {host_path!r} is outside the active workspace "
            f"{workspace!r}; stage commands can only reference files in the "
            f"mounted workspace."
        ) from exc
    return str(_CONTAINER_WORKSPACE / rel).replace("\\", "/")


def _translate_command(command: str, workspace: Path) -> str:
    """Replace any literal occurrences of the host workspace path in *command*
    with the container path.  This lets users write commands using regular
    pathlib.Path objects without manually computing /work/... strings.

    Windows: the host workspace contains backslashes ("C:\\Users\\...\\ws").
    After substituting the workspace prefix with "/work", any path component
    *after* the prefix (e.g. "\\data.fna") would still hold backslashes.
    A second pass normalises those tail components to forward slashes so the
    command is a valid POSIX path inside the container.
    """
    ws_str = str(workspace)
    container = str(_CONTAINER_WORKSPACE)
    # Both forward- and back-slashed forms (Windows users)
    out = command.replace(ws_str, container).replace(
        ws_str.replace("\\", "/"), container,
    )
    # Normalise backslashes that follow the /work prefix
    return re.sub(
        r"(/work)([\\/][^\s'\"<>|;&]*)",
        lambda m: m.group(1) + m.group(2).replace("\\", "/"),
        out,
    )


def _collect_external_mounts(
    args: tuple, kwargs: dict, workspace: Path,
) -> "tuple[dict[str, str], dict[str, str]]":
    """Scan call arguments for ``Path`` inputs that live *outside* the
    workspace and build (a) extra read-only-ish bind mounts and (b) a
    host→container string-translation map.

    Without this, a stage command that references e.g.
    ``/home/user/reads_R1.fastq.gz`` would point at a path that is
    neither mounted into the container nor rewritten by
    :func:`_translate_command` (which only touches workspace paths).

    Rules
    -----
    * A directory argument is mounted directly at ``/inputs/<n>``.
    * A file argument has its **parent directory** mounted (so sibling
      files — BAM ``.bai`` indexes, multi-part Bowtie2 indexes — come
      along) and the file path is rewritten to ``/inputs/<n>/<name>``.
    * An *index prefix* that does not itself exist but whose parent
      directory does (e.g. a Bowtie2 ``hg38`` prefix) is treated like a
      file: parent mounted, prefix rewritten.
    * Paths already inside the workspace, and ``StageResult`` objects
      (whose ``out_dir`` is always in the workspace), are left for the
      regular workspace translator.

    Returns
    -------
    ``(mounts, translation)`` where ``mounts`` is host-dir→container-dir
    and ``translation`` is host-path-string→container-path-string.
    """
    mounts: "dict[str, str]" = {}
    translation: "dict[str, str]" = {}
    _dir_index: "dict[str, str]" = {}

    def _container_dir_for(host_dir: Path) -> str:
        key = str(host_dir)
        if key not in _dir_index:
            cdir = str(_CONTAINER_INPUTS / str(len(_dir_index)))
            _dir_index[key] = cdir
            mounts[key] = cdir
        return _dir_index[key]

    def _handle_path(p: Path) -> None:
        resolved = Path(p).resolve()
        try:
            resolved.relative_to(workspace)
            return  # inside workspace — regular translator handles it
        except ValueError:
            pass
        if resolved.is_dir():
            cdir = _container_dir_for(resolved)
            translation[str(p)] = cdir
            translation[str(resolved)] = cdir
        elif resolved.exists() or resolved.parent.is_dir():
            # a real file, or an index prefix whose parent dir exists.
            # The parent dir is mounted at a space-free /inputs/<n>, so a
            # spaced *directory* is fine — only the basename survives into
            # the command.  An unsafe basename (space / shell metachar)
            # would silently corrupt the unquoted token in a recipe's
            # command (and can't be quoted generically because many
            # recipes wrap the whole command in `bash -c '…'`).  Fail
            # early with an actionable message instead.
            _reject_unsafe_basename(resolved)
            cdir = _container_dir_for(resolved.parent)
            cpath = f"{cdir}/{resolved.name}"
            translation[str(p)] = cpath
            translation[str(resolved)] = cpath
        # else: path doesn't resolve at all — leave it; the tool will
        # fail loudly with a clear "file not found" rather than silently.

    def _scan(v: Any) -> None:
        if isinstance(v, Path):
            _handle_path(v)
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

    return mounts, translation


def _apply_external_translation(
    command: str, translation: "dict[str, str]",
) -> str:
    """Rewrite host paths in *command* to their container paths.

    Longest host strings are replaced first so a file path is never
    partially rewritten by its own parent-directory entry.  Both the
    native and forward-slash forms are replaced (Windows hosts).
    """
    for host in sorted(translation, key=len, reverse=True):
        container = translation[host]
        command = command.replace(host, container)
        command = command.replace(host.replace("\\", "/"), container)
    return command
