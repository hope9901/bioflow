"""Environment self-check ("bioflow doctor").

Runs a short, fast battery of host checks so first-time users discover
configuration problems before they hit them mid-recipe.  Each check is a
pure function that returns a :class:`CheckResult`; ``run_checks`` is a
plain iterator over them so the CLI (and tests) can format the result
however they like.

Design notes
------------
* No check is allowed to raise — every failure mode becomes a
  :class:`CheckResult` with ``status="fail"`` and a one-line ``fix``
  hint.  Doctor must never be the reason `bioflow doctor` itself blows
  up.
* Each check is independent (no shared state) so users running
  ``bioflow doctor`` with restricted permissions still get partial
  information instead of an early abort.
* Checks split into three severities:
    - ``ok``    everything is fine, no action needed.
    - ``warn``  works but may be slow / degraded (e.g. low RAM, no GPU).
    - ``fail``  recipes will not work until the user acts.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal, Optional

Status = Literal["ok", "warn", "fail"]

# Minimum thresholds before a recipe is *likely* to succeed.  These are
# deliberately generous — the per-tool hardware filter
# (bioflow.core.compatibility) does the strict gating per recipe.
_MIN_PYTHON = (3, 9)
_MIN_CPU = 2
_WARN_CPU = 4
_MIN_RAM_GB = 4.0
_WARN_RAM_GB = 8.0
_MIN_DISK_GB = 10.0
_WARN_DISK_GB = 50.0
_SUPPORTED_ARCHES = {"x86_64", "arm64"}


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    fix: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "status": self.status, "message": self.message}
        if self.fix:
            d["fix"] = self.fix
        if self.detail:
            d["detail"] = self.detail
        return d


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_python() -> CheckResult:
    v = sys.version_info
    cur = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < _MIN_PYTHON:
        return CheckResult(
            name="python",
            status="fail",
            message=f"Python {cur} is older than the supported minimum 3.9.",
            fix="Install Python 3.9 or newer and recreate the virtualenv.",
            detail={"version": cur},
        )
    return CheckResult(
        name="python",
        status="ok",
        message=f"Python {cur}",
        detail={"version": cur},
    )


def _container_runtime() -> "tuple[Optional[str], Optional[str]]":
    """Return (cli_name, path) — prefers docker, falls back to podman.

    Podman ships a Docker-compatible CLI + API socket, so bioflow's
    sibling-container model works through it unchanged.  ``BIOFLOW_
    CONTAINER_RUNTIME`` forces a choice when both are installed.
    """
    forced = os.environ.get("BIOFLOW_CONTAINER_RUNTIME", "").strip().lower()
    candidates = [forced] if forced in ("docker", "podman") else ["docker", "podman"]
    for name in candidates:
        p = shutil.which(name)
        if p:
            return name, p
    return None, None


def _check_docker_cli() -> CheckResult:
    cli, path = _container_runtime()
    if not cli:
        return CheckResult(
            name="docker_cli",
            status="fail",
            message="no `docker` or `podman` executable on PATH.",
            fix=(
                "Install Docker Desktop (Windows/macOS), the docker engine "
                "(Linux), or Podman; then restart this shell."
            ),
        )
    return CheckResult(
        name="docker_cli",
        status="ok",
        message=f"{cli} CLI at {path}",
        detail={"runtime": cli, "path": path},
    )


def _check_docker_daemon() -> CheckResult:
    cli, _ = _container_runtime()
    if cli is None:
        return CheckResult(
            name="docker_daemon",
            status="fail",
            message="no docker/podman CLI — cannot probe daemon.",
            fix="Resolve the docker_cli check first.",
        )
    try:
        r = subprocess.run(
            [cli, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult(
            name="docker_daemon",
            status="fail",
            message=f"`{cli} info` could not run: {exc}",
            fix="Start Docker Desktop or `sudo systemctl start docker`.",
        )
    if r.returncode != 0:
        # Trim noisy lines, keep the first signal-bearing one.
        first_err = (r.stderr or r.stdout or "").strip().splitlines()
        msg = first_err[0] if first_err else f"non-zero exit from `{cli} info`"
        return CheckResult(
            name="docker_daemon",
            status="fail",
            message=f"{cli} daemon unreachable ({msg}).",
            fix=(
                "Start Docker Desktop (Windows/macOS) or "
                "`sudo systemctl start docker` (Linux). "
                "On Linux add your user to the `docker` group to avoid sudo. "
                "For Podman, `podman system service` exposes the API socket."
            ),
        )
    server = r.stdout.strip() or "unknown"
    return CheckResult(
        name="docker_daemon",
        status="ok",
        message=f"{cli} daemon reachable (server {server})",
        detail={"runtime": cli, "server_version": server},
    )


def _check_docker_socket() -> CheckResult:
    """Verify the sibling-container path is feasible.

    Linux/macOS: the host socket at /var/run/docker.sock must be
    readable by the current user.  Windows: Docker Desktop exposes its
    pipe via the docker CLI directly, so this check is informational
    only (no socket file on disk to test).
    """
    sysname = platform.system().lower()
    if sysname == "windows":
        return CheckResult(
            name="docker_socket",
            status="ok",
            message="Windows: docker pipe accessed via CLI (no socket file).",
            detail={"platform": sysname},
        )
    sock = Path("/var/run/docker.sock")
    if not sock.exists():
        return CheckResult(
            name="docker_socket",
            status="fail",
            message=f"{sock} does not exist.",
            fix=(
                "Start the docker engine.  On Linux check "
                "`systemctl status docker`."
            ),
        )
    if not os.access(sock, os.R_OK | os.W_OK):
        return CheckResult(
            name="docker_socket",
            status="fail",
            message=f"{sock} exists but the current user cannot read/write it.",
            fix=(
                "Add your user to the docker group "
                "(`sudo usermod -aG docker $USER`) and start a new shell, "
                "or run bioflow with sudo (not recommended)."
            ),
        )
    return CheckResult(
        name="docker_socket",
        status="ok",
        message=f"{sock} readable+writable.",
    )


def _check_cpu() -> CheckResult:
    try:
        import psutil  # noqa: PLC0415
        n = psutil.cpu_count(logical=True) or 1
    except Exception as exc:
        return CheckResult(
            name="cpu",
            status="warn",
            message=f"Could not detect CPU count: {exc}",
        )
    if n < _MIN_CPU:
        return CheckResult(
            name="cpu",
            status="fail",
            message=f"Only {n} logical CPU detected (minimum {_MIN_CPU}).",
            fix="Run on a host with at least 2 logical CPUs.",
            detail={"cpu_count": n},
        )
    if n < _WARN_CPU:
        return CheckResult(
            name="cpu",
            status="warn",
            message=f"{n} logical CPU — many recipes assume ≥ {_WARN_CPU}.",
            fix="Smaller cookbooks (download_taxon, ani_matrix) still work.",
            detail={"cpu_count": n},
        )
    return CheckResult(
        name="cpu",
        status="ok",
        message=f"{n} logical CPU",
        detail={"cpu_count": n},
    )


def _check_ram() -> CheckResult:
    try:
        import psutil  # noqa: PLC0415
        gb = psutil.virtual_memory().total / (1024 ** 3)
    except Exception as exc:
        return CheckResult(
            name="ram",
            status="warn",
            message=f"Could not detect RAM: {exc}",
        )
    if gb < _MIN_RAM_GB:
        return CheckResult(
            name="ram",
            status="fail",
            message=f"Only {gb:.1f} GB RAM (minimum {_MIN_RAM_GB:.0f} GB).",
            fix=(
                "Recipes that touch assembly / Kraken2 will OOM. "
                "Run on a host with ≥ 8 GB RAM for any non-trivial workflow."
            ),
            detail={"ram_gb": round(gb, 2)},
        )
    if gb < _WARN_RAM_GB:
        return CheckResult(
            name="ram",
            status="warn",
            message=(
                f"{gb:.1f} GB RAM — assembly / metagenomics recipes may swap."
            ),
            fix=(
                "Stick to download_taxon, ani_matrix, amr_vf_catalogue, or "
                "rnaseq_deg with Salmon — they fit in 8 GB."
            ),
            detail={"ram_gb": round(gb, 2)},
        )
    return CheckResult(
        name="ram",
        status="ok",
        message=f"{gb:.1f} GB RAM",
        detail={"ram_gb": round(gb, 2)},
    )


def _reclaim_hint(workspace: Path) -> str:
    """What is actually using space here, and the command that frees it.

    A bare "not enough disk" leaves the user guessing which directory to delete;
    the stage cache and provisioned databases are the two things bioflow put
    there, so name them with sizes.
    """
    try:
        from bioflow.core.diskusage import cache_usage, human  # noqa: PLC0415

        cached = cache_usage(workspace)
    except Exception:  # pragma: no cover - reporting must never break the check
        return ""
    if not cached:
        return ""
    total = sum(e.bytes for e in cached)
    return (
        f"{len(cached)} cached stage results are using {human(total)} — "
        f"`bioflow cache size -w {workspace}` to inspect, "
        f"`bioflow cache clear -w {workspace}` to reclaim. "
        f"Provisioned databases: `bioflow db size` / `bioflow db gc <name>`."
    )


def _check_disk(workspace: Path) -> CheckResult:
    try:
        usage = shutil.disk_usage(workspace)
        free_gb = usage.free / (1024 ** 3)
    except OSError as exc:
        return CheckResult(
            name="disk",
            status="fail",
            message=f"Cannot read disk usage for {workspace}: {exc}",
            fix="Pass a writable --workspace path to bioflow doctor.",
        )
    if free_gb < _MIN_DISK_GB:
        return CheckResult(
            name="disk",
            status="fail",
            message=(
                f"{free_gb:.1f} GB free at {workspace} "
                f"(minimum {_MIN_DISK_GB:.0f} GB)."
            ),
            fix=(
                _reclaim_hint(workspace)
                or "Free space, or rerun with `--workspace <bigger-disk>` "
                   "so caches and Docker volumes land on a roomy partition."
            ),
            detail={"disk_free_gb": round(free_gb, 2), "path": str(workspace)},
        )
    if free_gb < _WARN_DISK_GB:
        return CheckResult(
            name="disk",
            status="warn",
            message=(
                f"{free_gb:.1f} GB free at {workspace} — eukaryote_assembly / "
                f"metagenome_assembly may need ≥ {_WARN_DISK_GB:.0f} GB."
            ),
            fix=_reclaim_hint(workspace) or None,
            detail={"disk_free_gb": round(free_gb, 2), "path": str(workspace)},
        )
    return CheckResult(
        name="disk",
        status="ok",
        message=f"{free_gb:.1f} GB free at {workspace}",
        detail={"disk_free_gb": round(free_gb, 2), "path": str(workspace)},
    )


def _check_arch() -> CheckResult:
    from bioflow.core.hardware import _ARCH_ALIASES  # noqa: PLC0415

    raw = platform.machine()
    arch = _ARCH_ALIASES.get(raw.lower(), raw.lower())
    if arch not in _SUPPORTED_ARCHES:
        return CheckResult(
            name="arch",
            status="warn",
            message=(
                f"Architecture {arch!r} is not in the supported set "
                f"{sorted(_SUPPORTED_ARCHES)}; some BioContainer images may "
                f"not have a matching tag."
            ),
            detail={"arch": arch, "raw": raw},
        )
    return CheckResult(
        name="arch",
        status="ok",
        message=arch,
        detail={"arch": arch},
    )


def _check_registry(registry_dir: Optional[Path] = None) -> CheckResult:
    from bioflow.core.registry import (  # noqa: PLC0415
        default_registry_dir,
        load_registry,
    )

    reg = registry_dir or default_registry_dir()
    if not (reg / "tools").is_dir():
        return CheckResult(
            name="registry",
            status="fail",
            message=f"No registry under {reg} (missing tools/).",
            fix=(
                "Run from a bioflow git checkout, or reinstall the wheel — "
                "the bundled registry was not packaged."
            ),
            detail={"registry_dir": str(reg)},
        )
    try:
        tools = load_registry(reg)
    except Exception as exc:
        return CheckResult(
            name="registry",
            status="fail",
            message=f"Registry under {reg} failed to load: {exc}",
            fix="Run `bioflow tools` to see the underlying loader warnings.",
            detail={"registry_dir": str(reg)},
        )
    if not tools:
        return CheckResult(
            name="registry",
            status="fail",
            message=f"Registry at {reg} loaded zero tools.",
            fix="Re-clone the repo or `pip install --force-reinstall bioflow`.",
            detail={"registry_dir": str(reg), "tool_count": 0},
        )
    return CheckResult(
        name="registry",
        status="ok",
        message=f"{len(tools)} tools loaded from {reg}",
        detail={"registry_dir": str(reg), "tool_count": len(tools)},
    )


def _check_writable(label: str, path: Path, severity_on_fail: Status) -> CheckResult:
    """Confirm we can create files under *path* (creating it if missing)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(
            name=label,
            status=severity_on_fail,
            message=f"Cannot create {path}: {exc}",
            fix=f"Grant the current user write access to {path.parent}.",
            detail={"path": str(path)},
        )
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".bioflow_doctor_", dir=path, delete=True
        ):
            pass
    except OSError as exc:
        return CheckResult(
            name=label,
            status=severity_on_fail,
            message=f"{path} exists but is not writable: {exc}",
            fix=f"chmod / chown so the current user can write to {path}.",
            detail={"path": str(path)},
        )
    return CheckResult(
        name=label,
        status="ok",
        message=f"{path} writable",
        detail={"path": str(path)},
    )


def _check_home_config() -> CheckResult:
    return _check_writable(
        "home_config", Path.home() / ".bioflow", severity_on_fail="fail"
    )


def _check_workspace(workspace: Path) -> CheckResult:
    return _check_writable("workspace", workspace, severity_on_fail="fail")


def _check_gpu() -> CheckResult:
    """GPU is purely informational — incompatible recipes are already
    filtered by `bioflow tools` against the hardware profile."""
    try:
        from bioflow.core.hardware import _detect_gpu  # noqa: PLC0415
        present, names, cuda = _detect_gpu()
    except Exception as exc:
        return CheckResult(
            name="gpu",
            status="warn",
            message=f"GPU probe failed: {exc}",
        )
    if not present:
        return CheckResult(
            name="gpu",
            status="ok",
            message="no GPU detected (CPU-only recipes will still run)",
            detail={"present": False},
        )
    return CheckResult(
        name="gpu",
        status="ok",
        message=(
            f"{len(names)} GPU(s): {', '.join(names) or 'unknown model'}"
            + (f" (CUDA {cuda})" if cuda else "")
        ),
        detail={"present": True, "names": names, "cuda": cuda},
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

CheckFn = Callable[[], CheckResult]


def _resolve_workspace(workspace: Optional[Path]) -> Path:
    return (workspace or Path.cwd()).resolve()


def run_checks(
    workspace: Optional[Path] = None,
    registry_dir: Optional[Path] = None,
) -> list[CheckResult]:
    """Run every check and return results in declaration order.

    No check is allowed to raise — any unexpected exception is converted
    to a ``fail`` result so the surrounding command still finishes and
    other checks still run.
    """
    ws = _resolve_workspace(workspace)
    pairs: list[tuple[str, CheckFn]] = [
        ("python", _check_python),
        ("arch", _check_arch),
        ("docker_cli", _check_docker_cli),
        ("docker_daemon", _check_docker_daemon),
        ("docker_socket", _check_docker_socket),
        ("cpu", _check_cpu),
        ("ram", _check_ram),
        ("disk", lambda: _check_disk(ws)),
        ("gpu", _check_gpu),
        ("registry", lambda: _check_registry(registry_dir)),
        ("home_config", _check_home_config),
        ("workspace", lambda: _check_workspace(ws)),
    ]
    results: list[CheckResult] = []
    for name, fn in pairs:
        try:
            results.append(fn())
        except Exception as exc:  # belt-and-braces — checks shouldn't raise
            results.append(
                CheckResult(
                    name=name,
                    status="fail",
                    message=f"unexpected error inside check: {exc}",
                    fix="File a bug at https://github.com/hope9901/bioflow/issues.",
                )
            )
    return results


def summarize(results: Iterable[CheckResult]) -> dict[Status, int]:
    """Count by status — used by the CLI for the trailing banner."""
    out: dict[Status, int] = {"ok": 0, "warn": 0, "fail": 0}
    for r in results:
        out[r.status] = out.get(r.status, 0) + 1
    return out


def exit_code(results: Iterable[CheckResult]) -> int:
    """Process exit code: 1 if any fail, else 0 (warnings do not block)."""
    return 1 if any(r.status == "fail" for r in results) else 0
