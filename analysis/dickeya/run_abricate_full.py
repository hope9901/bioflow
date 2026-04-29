"""ABRicate × 262 genomes × 3 databases (vfdb, card, plasmidfinder).

Builds a full resistome+virulome+plasmid catalogue across the genus,
then aggregates a presence matrix for downstream visualisation.
"""
from __future__ import annotations
import sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
GENOMES  = ANALYSIS / "genomes_full"
ABR      = ANALYSIS / "abricate_full"; ABR.mkdir(exist_ok=True)
WS_HOST  = str(ANALYSIS); WS_CTR = "/work"
backend  = DockerBackend()

DBS = ["vfdb", "card", "plasmidfinder"]
samples = sorted(p.stem for p in GENOMES.glob("*.fna"))
print(f"{len(samples)} genomes × {len(DBS)} DBs = {len(samples)*len(DBS)} runs")


def run_one(args: tuple[str, str]) -> tuple[str, str, int]:
    sample, db = args
    out = ABR / f"{sample}.{db}.tsv"
    if out.exists() and out.stat().st_size > 50:
        return sample, db, -1   # cached
    cmd = (
        f"sh -c 'abricate --db {db} --threads 1 --quiet "
        f"{WS_CTR}/genomes_full/{sample}.fna > "
        f"{WS_CTR}/abricate_full/{sample}.{db}.tsv'"
    )
    r = backend.run(
        image="staphb/abricate:1.2.0", command=cmd,
        mounts={WS_HOST: WS_CTR}, cpu=1, ram_gb=1, workdir=WS_CTR,
    )
    return sample, db, r.exit_code


print("\nStarting ABRicate batch (12 parallel × 1 cpu) …")
t0 = time.time()
done = 0; cached = 0; failed: list[tuple] = []
tasks = [(s, db) for s in samples for db in DBS]
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = {ex.submit(run_one, t): t for t in tasks}
    for fut in as_completed(futs):
        s, db, rc = fut.result()
        done += 1
        if rc == -1:
            cached += 1
        elif rc != 0:
            failed.append((s, db))
        if done % 50 == 0:
            elapsed = time.time() - t0
            rate = done / max(elapsed, 1)
            eta = (len(tasks) - done) / max(rate, 1e-3)
            print(f"  [{done:4d}/{len(tasks)}]  elapsed={elapsed/60:.1f}m  "
                  f"ETA={eta/60:.1f}m  cached={cached}  failed={len(failed)}",
                  flush=True)

print(f"\nDone. cached={cached}  failed={len(failed)}")
print(f"Total wall: {(time.time()-t0)/60:.1f} min")
if failed:
    print(f"failed runs: {failed[:10]}")
