"""Concurrency helpers — worker-count resolution, progress bar, retry bumps.

Shared by ``Stage.map``/``starmap``/``imap_unordered`` and by
``Stage._run_once`` (which consults :func:`_bump_resources` between
retries).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, Union

from bioflow.core.logger import get_logger

from bioflow.sdk._result import StageResult

log = get_logger()


_ProgressCallback = Callable[[int, int, StageResult], None]


def _resolve_parallel(parallel: Union[int, str], cpu_per_stage: int) -> int:
    """Translate ``parallel="auto"`` into a concrete worker count.

    ``parallel=N`` (int) is honoured as-is, clamped to ≥ 1.
    ``parallel="auto"`` returns ``max(1, host_cpu // cpu_per_stage)`` so
    the host's logical CPU count is filled without oversubscription.
    """
    if isinstance(parallel, str):
        if parallel.lower() != "auto":
            raise ValueError(
                f"parallel must be int or 'auto', got {parallel!r}"
            )
        host_cpu = os.cpu_count() or 1
        return max(1, host_cpu // max(1, cpu_per_stage))
    return max(1, int(parallel))


class _AnsiProgress:
    """Minimal in-place progress bar — no tqdm dependency.

    ``update(i, n, sr)`` paints
        [###----- ]  4/12  cached=1  fail=0  stage_name
    on a single TTY line.  Falls back to per-completion log lines on
    non-TTY (CI logs, redirected stdout).
    """

    BAR_WIDTH = 28

    def __init__(self, label: str, total: int) -> None:
        self.label = label
        self.total = total
        self.cached = 0
        self.failed = 0
        self.tty = sys.stderr.isatty()
        self.last = -1
        self._lock = threading.Lock()
        self._t0 = time.time()

    def __call__(self, done: int, total: int, sr: StageResult) -> None:
        with self._lock:
            if sr.cached:
                self.cached += 1
            if not sr.ok:
                self.failed += 1
            elapsed = time.time() - self._t0
            rate = done / max(elapsed, 0.01)
            eta = (total - done) / max(rate, 1e-3)
            if self.tty:
                filled = int(self.BAR_WIDTH * done / max(total, 1))
                bar = "#" * filled + "-" * (self.BAR_WIDTH - filled)
                msg = (
                    f"\r  [{bar}] {done:>4d}/{total}  "
                    f"cached={self.cached}  fail={self.failed}  "
                    f"eta={eta:>4.0f}s  {self.label}"
                )
                sys.stderr.write(msg)
                sys.stderr.flush()
                if done == total:
                    sys.stderr.write("\n")
                    sys.stderr.flush()
            else:
                # Non-TTY: emit once every ~5% so logs aren't flooded
                pct = int(100 * done / max(total, 1))
                if pct // 5 != self.last // 5 or done == total:
                    self.last = pct
                    log.info(
                        f"{self.label}: {done}/{total} "
                        f"({pct}%)  cached={self.cached}  fail={self.failed}"
                    )


def _bump_resources(
    cpu: int, ram_gb: float, recipe: dict,
) -> tuple[int, float]:
    """Apply ``retry_with`` directives to one (cpu, ram_gb) pair.

    Each value can be:
      * a string ending in 'x' / 'X'  → multiplier (e.g. ``"2x"``)
      * a numeric int / float         → absolute override
      * anything else                 → ignored with a warning
    """
    new_cpu = cpu
    new_ram = ram_gb
    for key, val in (recipe or {}).items():
        if key not in ("cpu", "ram_gb"):
            log.warning(f"retry_with: ignoring unknown key {key!r}")
            continue
        try:
            if isinstance(val, str) and val.lower().endswith("x"):
                mult = float(val[:-1])
                if key == "cpu":
                    new_cpu = max(1, int(cpu * mult))
                else:
                    new_ram = ram_gb * mult
            elif isinstance(val, (int, float)):
                if key == "cpu":
                    new_cpu = max(1, int(val))
                else:
                    new_ram = float(val)
            else:
                log.warning(
                    f"retry_with[{key}]: invalid value {val!r}; "
                    "expected int / float or 'Nx' string"
                )
        except (TypeError, ValueError) as exc:
            log.warning(f"retry_with[{key}]: {exc}; leaving unchanged")
    return new_cpu, new_ram


__all__ = [
    "_resolve_parallel",
    "_AnsiProgress",
    "_bump_resources",
    "_ProgressCallback",
]


# Optional public-callback alias kept for backward compatibility with
# anyone importing the old name from bioflow.sdk.
ProgressCallback = _ProgressCallback
