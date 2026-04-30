"""Phase-1C demo — input-hash caching with the @stage decorator.

Run twice; the second run should be near-instant (all cache hits).
"""
from __future__ import annotations

import sys, time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bioflow import stage, set_workspace, clear_cache

WS = Path(__file__).resolve().parent / "_cache_demo_ws"
set_workspace(WS)


@stage(image="busybox:latest", cpu=1, ram_gb=1)
def slow_stamp(idx: int, *, out_dir):
    return f"sh -c 'sleep 1 && echo idx={idx} > {out_dir}/log.txt'"


def time_block(label, fn):
    t0 = time.time()
    out = fn()
    dt = time.time() - t0
    print(f"  {label}: {dt:.1f}s")
    return out


print("\n=== First run — cold cache ===")
results = time_block("8 tasks × 4-parallel (cold)",
                     lambda: slow_stamp.map(list(range(8)), parallel=4))
print(f"  cached count: {sum(r.cached for r in results)}/8")

print("\n=== Second run — same inputs, cache should hit ===")
results = time_block("8 tasks × 4-parallel (warm)",
                     lambda: slow_stamp.map(list(range(8)), parallel=4))
print(f"  cached count: {sum(r.cached for r in results)}/8")

print("\n=== Third run — extend by 2 new inputs ===")
results = time_block("10 tasks × 4-parallel",
                     lambda: slow_stamp.map(list(range(10)), parallel=4))
print(f"  cached count: {sum(r.cached for r in results)}/10")

print("\n=== After clear_cache() — all cold again ===")
clear_cache(WS)
results = time_block("8 tasks × 4-parallel (after clear)",
                     lambda: slow_stamp.map(list(range(8)), parallel=4))
print(f"  cached count: {sum(r.cached for r in results)}/8")
