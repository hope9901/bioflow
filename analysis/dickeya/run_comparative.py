"""Dickeya comparative genomics - orchestrate Prokka + FastANI + Roary
using bioflow's DockerBackend (sibling-container pattern).

Steps:
  1. Re-annotate all 13 RefSeq assemblies with Prokka for consistency.
  2. Compute pairwise ANI with FastANI (all-vs-all).
  3. Build pangenome + core-gene alignment with Roary.

Outputs land under analysis/dickeya/{prokka,fastani,roary}/.
"""
from __future__ import annotations

import sys
import time

# cp949-safe stdout on Korean Windows
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bioflow.core.runner import DockerBackend  # noqa: E402

ANALYSIS = ROOT / "analysis" / "dickeya"
INPUTS   = ANALYSIS / "inputs"
PROKKA   = ANALYSIS / "prokka"
FASTANI  = ANALYSIS / "fastani"
ROARY    = ANALYSIS / "roary"

for d in (PROKKA, FASTANI, ROARY):
    d.mkdir(parents=True, exist_ok=True)

# Bioflow's DockerBackend mounts host paths into the container.
WS_HOST = str(ANALYSIS.resolve())
WS_CTR  = "/work"   # path inside container

backend = DockerBackend()


def run_in_container(*, image: str, command: str, cpu: int, ram_gb: float,
                     label: str) -> int:
    print(f"\n=== {label} ===")
    print(f"    image={image}")
    print(f"    cmd={command[:120]}{'...' if len(command) > 120 else ''}")
    t0 = time.time()
    result = backend.run(
        image=image,
        command=command,
        mounts={WS_HOST: WS_CTR},
        cpu=cpu, ram_gb=ram_gb,
        workdir=WS_CTR,
        log_callback=lambda line: None,   # silent; logs are huge
    )
    dt = time.time() - t0
    print(f"    exit={result.exit_code}  elapsed={dt:.1f}s")
    if result.exit_code != 0:
        print("--- STDERR/STDOUT TAIL ---")
        print((result.stderr or result.stdout)[-1500:])
    return result.exit_code


# ────────────────────────────── Step 1: Prokka ──────────────────────────────
samples = sorted(p.stem for p in INPUTS.glob("*.fna"))
print(f"Step 1 - Prokka re-annotation of {len(samples)} genomes (parallel x4)")


def prokka_one(sample: str) -> tuple[str, int]:
    out_sub = f"prokka/{sample}"
    cmd = (
        f"prokka --outdir {WS_CTR}/{out_sub} --prefix {sample} "
        f"--cpus 2 --kingdom Bacteria --genus Dickeya --usegenus --force "
        f"--quiet {WS_CTR}/inputs/{sample}.fna"
    )
    rc = run_in_container(
        image="staphb/prokka:1.14.6",
        command=cmd,
        cpu=2, ram_gb=4,
        label=f"Prokka [{sample}]",
    )
    return sample, rc


prokka_failures = []
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(prokka_one, s): s for s in samples}
    for fut in as_completed(futs):
        sid, rc = fut.result()
        if rc != 0:
            prokka_failures.append(sid)

if prokka_failures:
    print(f"\nProkka failed on: {prokka_failures}")
    sys.exit(1)

# Stage all .gff files into a flat dir for Roary
GFF_FLAT = ROARY / "_gff_in"; GFF_FLAT.mkdir(exist_ok=True)
for s in samples:
    src = PROKKA / s / f"{s}.gff"
    dst = GFF_FLAT / f"{s}.gff"
    if src.exists() and not dst.exists():
        dst.write_bytes(src.read_bytes())

# ─────────────────────────────── Step 2: FastANI ─────────────────────────────
print("\nStep 2 - FastANI all-vs-all")
genome_list = FASTANI / "genome_list.txt"
genome_list.write_text(
    "\n".join(f"{WS_CTR}/inputs/{s}.fna" for s in samples) + "\n",
    encoding="utf-8",
)
rc = run_in_container(
    image="staphb/fastani:1.34",
    command=(
        f"fastANI --ql {WS_CTR}/fastani/genome_list.txt "
        f"--rl {WS_CTR}/fastani/genome_list.txt "
        f"-o {WS_CTR}/fastani/ani_matrix.tsv -t 8 "
        f"--matrix"
    ),
    cpu=8, ram_gb=8,
    label="FastANI",
)
if rc != 0:
    sys.exit(1)

# ─────────────────────────────── Step 3: Roary ───────────────────────────────
print("\nStep 3 - Roary pangenome")
# Roary writes to its --f dir (must NOT exist) - point it at a fresh subdir.
rc = run_in_container(
    image="staphb/roary:3.13.0",
    command=(
        f"sh -c 'rm -rf {WS_CTR}/roary/out && "
        f"roary -p 8 -f {WS_CTR}/roary/out -e -n -v "
        f"{WS_CTR}/roary/_gff_in/*.gff'"
    ),
    cpu=8, ram_gb=16,
    label="Roary",
)
if rc != 0:
    sys.exit(1)

print("\nALL STEPS COMPLETE.")
print(f"  Prokka  -> {PROKKA}")
print(f"  FastANI -> {FASTANI}/ani_matrix.tsv")
print(f"  Roary   -> {ROARY}/out/")
