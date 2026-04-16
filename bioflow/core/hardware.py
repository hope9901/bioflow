"""Hardware profiler.

Detects CPU / RAM / GPU / disk / architecture / Docker availability on the host.
Returned as a Pydantic model for easy JSON serialization and registry matching.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import psutil
from pydantic import BaseModel


class HardwareProfile(BaseModel):
    cpu_count: int
    ram_gb: float
    disk_free_gb: float
    arch: str
    os: str
    gpu_present: bool
    gpu_names: list[str] = []
    cuda_version: Optional[str] = None
    docker_available: bool = False


def _detect_gpu() -> tuple[bool, list[str], Optional[str]]:
    """Return (present, names, cuda_version)."""
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        names: list[str] = []
        for i in range(n):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            raw = pynvml.nvmlDeviceGetName(h)
            names.append(raw.decode() if isinstance(raw, bytes) else raw)
        try:
            cuda = str(pynvml.nvmlSystemGetCudaDriverVersion())
        except Exception:
            cuda = None
        pynvml.nvmlShutdown()
        return n > 0, names, cuda
    except Exception:
        return False, [], None


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, check=False
        )
        return r.returncode == 0
    except Exception:
        return False


def detect(data_dir: Path = Path.cwd()) -> HardwareProfile:
    """Detect the current host's hardware profile."""
    cpu = psutil.cpu_count(logical=True) or 1
    ram_gb = psutil.virtual_memory().total / (1024**3)
    disk_free_gb = shutil.disk_usage(data_dir).free / (1024**3)
    gpu_present, gpu_names, cuda = _detect_gpu()
    return HardwareProfile(
        cpu_count=cpu,
        ram_gb=round(ram_gb, 2),
        disk_free_gb=round(disk_free_gb, 2),
        arch=platform.machine().lower(),
        os=platform.system().lower(),
        gpu_present=gpu_present,
        gpu_names=gpu_names,
        cuda_version=cuda,
        docker_available=_docker_available(),
    )
