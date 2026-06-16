# genomes_small — comparative-genomics e2e fixture

A tiny set of bacterial-ish genomes for full end-to-end tests of the
comparative-genomics recipes (AMR cataloguing, ANI, pangenome).

| File | What |
|---|---|
| `genome1.fna` | phiX174 (`NC_001422.1`, 5386 bp) |
| `genome2.fna` | phiX174 with 25 deterministic SNPs (seed 7) |

Two near-identical 5.4 kb genomes are enough to exercise the
fan-out → converge shape of these recipes (ABRicate × genomes × DBs,
all-vs-all FastANI, Prokka × genomes → Roary) in seconds, while
remaining real FASTA that the tools accept.

## Regeneration

```python
# genome1 = phiX174 (data/test/phix_small/reference.fa)
# genome2 = same with 25 SNPs at random.Random(7) positions
```

See the generation snippet in the commit that introduced this fixture.

## Used by

`tests/integration/test_full_pipeline_e2e.py` — `amr_vf_catalogue`
(and, as added, `ani_matrix` / `pangenome`).
