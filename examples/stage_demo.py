"""Phase-1A demo — `@stage` decorator on real Docker.

Demonstrates:
  * Single-call execution
  * Auto-injection of out_dir
  * Automatic host-to-container path translation
  * Parallel fan-out via .map(parallel=N)

Run with:
    python examples/stage_demo.py

Requires Docker Desktop / engine reachable.
"""
from __future__ import annotations

import sys
from pathlib import Path

# cp949-safe stdout (we already shipped this fix in cli.py — same here)
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

# Make bioflow importable from a checkout (no install needed)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bioflow import stage, set_workspace

WS = Path(__file__).resolve().parent.parent / "examples" / "_stage_demo_ws"
set_workspace(WS)


# --------------------------------------------------------------------- demo 1
@stage(image="busybox:latest", cpu=1, ram_gb=1)
def hello(name: str, *, out_dir):
    return f"echo 'hello, {name}!' > {out_dir}/greeting.txt"


print("\n=== Demo 1 — single call, auto out_dir ===")
result = hello("dickeya")
print(f"  ok={result.ok}  out_dir={result.out_dir.name}")
greeting = result.out_dir / "greeting.txt"
if greeting.exists():
    print(f"  greeting -> {greeting.read_text().strip()}")


# --------------------------------------------------------------------- demo 2
@stage(image="busybox:latest", cpu=1, ram_gb=1)
def stamp(idx: int, *, out_dir):
    return f"sh -c 'sleep 1 && echo iteration={idx} > {out_dir}/log.txt'"


print("\n=== Demo 2 — fan-out × 8 with parallel=4 ===")
import time
t0 = time.time()
results = stamp.map(list(range(8)), parallel=4)
elapsed = time.time() - t0
print(f"  ran {len(results)} tasks in {elapsed:.1f}s "
      f"(would be ~8s sequentially, ~2s with 4-parallel)")
print(f"  all OK: {all(r.ok for r in results)}")
print(f"  unique out_dirs: {len({r.out_dir for r in results})}")


# --------------------------------------------------------------------- demo 3
print("\n=== Demo 3 — host path inside workspace is auto-translated ===")
data_file = WS / "input.txt"
data_file.write_text("ACGTACGTACGT\n")


@stage(image="busybox:latest", cpu=1, ram_gb=1)
def count(infile: Path, *, out_dir):
    return f"wc -c {infile} > {out_dir}/wc.txt"


r = count(data_file)
print(f"  host file: {data_file}")
print(f"  command sent: {r.command!r}")
wc = r.out_dir / "wc.txt"
if wc.exists():
    print(f"  wc result: {wc.read_text().strip()}")

print("\nAll demos OK.")
