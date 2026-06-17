#!/usr/bin/env python
"""Regenerate the WGBS methylation e2e fixture (data/test/methyl_small/).

Deterministic (seed=42).  Produces directional paired-end bisulfite
reads from the committed phiX174 ``genome.fa``: unmethylated C's are
converted to T, while CpG C's stay methylated ~70 % of the time so
methylKit recovers a real, coherent CpG methylation level.

Directional library semantics matter — R2 is the reverse complement of
the *same* bisulfite-converted strand R1 came from (so R2 carries the
G->A pattern Bismark expects), NOT an independently converted strand.
Half the pairs come from the top strand, half from the bottom, so both
strand classes get coverage and all pairs map at ~100 %.

Run from the repo root::

    python scripts/gen_methyl_fixture.py
"""
from __future__ import annotations

import gzip
import random
from pathlib import Path

SEED = 42
READLEN = 80
INSERT = 200
N_PAIRS = 3000
CPG_METH = 0.70  # fraction of reads where a CpG C stays methylated

OUT = Path(__file__).resolve().parents[1] / "data" / "test" / "methyl_small"

_C = {"A": "T", "T": "A", "G": "C", "C": "G", "N": "N"}


def revcomp(s: str) -> str:
    return "".join(_C[c] for c in reversed(s))


def bisulfite(s: str, rng: random.Random) -> str:
    out = []
    for i, c in enumerate(s):
        if c == "C":
            is_cpg = (i + 1 < len(s) and s[i + 1] == "G")
            if is_cpg and rng.random() < CPG_METH:
                out.append("C")        # methylated CpG → stays C
            else:
                out.append("T")        # everything else converts
        else:
            out.append(c)
    return "".join(out)


def main() -> None:
    rng = random.Random(SEED)
    seq = "".join(
        line.strip().upper()
        for line in (OUT / "genome.fa").read_text().splitlines()
        if not line.startswith(">")
    )
    g = len(seq)
    qual = "I" * READLEN  # Phred 40

    r1_lines: list[str] = []
    r2_lines: list[str] = []
    for n in range(1, N_PAIRS + 1):
        p = rng.randint(0, g - INSERT - 1)
        frag = seq[p:p + INSERT]
        origin = revcomp(frag) if n % 2 == 0 else frag   # OB / OT
        conv = bisulfite(origin, rng)                    # one consistent conversion
        r1 = conv[:READLEN]
        r2 = revcomp(conv[-READLEN:])
        name = f"phix_read{n:05d}"
        r1_lines += [f"@{name}", r1, "+", qual]
        r2_lines += [f"@{name}", r2, "+", qual]

    # mtime=0 so the .gz is byte-reproducible (gzip otherwise stamps the
    # current time into the header, defeating a deterministic fixture).
    for fname, lines in (("sample01_R1.fastq.gz", r1_lines),
                         ("sample01_R2.fastq.gz", r2_lines)):
        raw = ("\n".join(lines) + "\n").encode()
        with gzip.GzipFile(str(OUT / fname), "wb", mtime=0) as fh:
            fh.write(raw)

    print(f"genome {g} bp; wrote {N_PAIRS} read pairs (readlen {READLEN})")


if __name__ == "__main__":
    main()
