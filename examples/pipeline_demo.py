"""Demo — @pipeline composition + show_graph + dry_run."""
from __future__ import annotations
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bioflow import stage, pipeline, set_workspace, clear_cache

WS = Path(__file__).resolve().parent / "_pipeline_demo_ws"
set_workspace(WS)
clear_cache(WS)


# ── Three stages with declared dependencies ─────────────────────────────────

@stage(image="busybox:latest", cpu=1, ram_gb=1)
def fetch(item, *, out_dir):
    return f"sh -c 'echo fetched {item} > {out_dir}/data.txt'"


@stage(image="busybox:latest", cpu=2, ram_gb=2, depends_on=fetch)
def process(fetch_result, *, out_dir):
    return (
        f"sh -c 'cat {fetch_result.out_dir}/data.txt | tr a-z A-Z "
        f"> {out_dir}/processed.txt'"
    )


@stage(image="busybox:latest", cpu=4, ram_gb=4, depends_on=process)
def aggregate(processed_results, *, out_dir):
    cat_inputs = " ".join(
        f"{r.out_dir}/processed.txt" for r in processed_results
    )
    return f"sh -c 'cat {cat_inputs} > {out_dir}/all.txt && wc -l {out_dir}/all.txt'"


# ── Pipeline composes them with normal Python ──────────────────────────────

@pipeline(
    stages=[fetch, process, aggregate],
    description="Demo: fetch → process (per-item) → aggregate",
)
def demo_pipeline(items):
    """Three-stage demonstration of @pipeline composition."""
    fetched = fetch.map(items, parallel="auto", progress=True)
    processed = process.map(fetched, parallel="auto", progress=True)
    return aggregate(processed)


# ── 1. Inspect the DAG without running anything ─────────────────────────────

print("=== show_graph() ===")
demo_pipeline.show_graph()

print("\n=== dry_run() ===")
plan = demo_pipeline.dry_run()
print(f"  pipeline:    {plan['pipeline']}")
print(f"  description: {plan['description']}")
print(f"  n_stages:    {plan['n_stages']}")
print(f"  total_cpu:   {plan['total_cpu']}")
print(f"  total_ram:   {plan['total_ram_gb']} GB")

# ── 2. Actually run it ──────────────────────────────────────────────────────

print("\n=== running pipeline ===")
t0 = time.time()
result = demo_pipeline(items=["alpha", "beta", "gamma", "delta"])
print(f"\n  pipeline returned: ok={result.ok}, out_dir={result.out_dir}")
print(f"  total wall: {time.time()-t0:.1f}s")

# ── 3. Re-run — fully cached ───────────────────────────────────────────────
print("\n=== re-running pipeline (should be all cache hits) ===")
t0 = time.time()
result = demo_pipeline(items=["alpha", "beta", "gamma", "delta"])
print(f"  total wall: {time.time()-t0:.1f}s")
