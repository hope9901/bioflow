"""Smoke-test candidate tools against bundled test datasets.

Usage (to be implemented in step 10):
    python update/benchmark.py --candidate update/candidates/2026-04/<tool>.yaml

Each candidate is run on `data/test/<matching>/` and checked for:
  - container pulls
  - produces expected output artifacts
  - completes within a generous wall-time budget
"""

from __future__ import annotations


def main() -> int:
    raise NotImplementedError("Implement in step 10 (update pipeline).")


if __name__ == "__main__":
    raise SystemExit(main())
