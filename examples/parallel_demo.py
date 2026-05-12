"""Demo — auto parallelism + progress + starmap + imap_unordered."""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bioflow import stage, set_workspace, clear_cache

WS = Path(__file__).resolve().parent / "_parallel_demo_ws"
set_workspace(WS)
clear_cache(WS)


@stage(image="busybox:latest", cpu=2, ram_gb=1, cache=False)
def task(i):
    return f"sh -c 'sleep 1 && echo task {i} done'"


@stage(image="busybox:latest", cpu=2, ram_gb=1, cache=False)
def two_arg(a, b):
    return f"sh -c 'sleep 1 && echo {a}+{b}'"


print(f"Host CPUs: {os.cpu_count()}, stage cpu=2 → 'auto' resolves to "
      f"~{(os.cpu_count() or 1) // 2}")

# 1. parallel="auto"
print("\n=== 12 tasks × parallel='auto' (with progress bar) ===")
t0 = time.time()
results = task.map(range(12), parallel="auto", progress=True)
print(f"  total: {time.time()-t0:.1f}s, all ok: {all(r.ok for r in results)}")

# 2. starmap
print("\n=== starmap: 6 two-arg tasks × parallel=4 ===")
t0 = time.time()
results = two_arg.starmap(
    [(i, i*10) for i in range(6)],
    parallel=4, progress=True,
)
print(f"  total: {time.time()-t0:.1f}s")

# 3. imap_unordered streaming
print("\n=== imap_unordered: stream as they complete ===")
t0 = time.time()
gen = task.imap_unordered(range(6), parallel=3)
for i, sr in enumerate(gen, 1):
    print(f"  result {i}/6 arrived at +{time.time()-t0:.1f}s  ok={sr.ok}")
