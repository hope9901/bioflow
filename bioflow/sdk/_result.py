"""Return type emitted by every ``@stage`` call."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class StageResult:
    """Returned by every stage call.  ``out_dir`` is the absolute host path
    that the stage's command was told to write into; downstream stages
    pass it (or files inside it) as inputs."""
    stage: str
    out_dir: Path
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    cached: bool = False
    cache_key: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0
