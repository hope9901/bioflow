# cafe_small — gene-family evolution e2e fixture

A tiny ultrametric tree + gene-family count matrix for a full
end-to-end test of the `cafe_evolution` recipe (CAFE5).

| File | What |
|---|---|
| `tree.nwk` | ultrametric 4-taxon Newick `((A,B),(C,D))`, root-to-tip = 2 |
| `families.tsv` | CAFE5-format matrix: 60 families × 4 species (A–D) |

60 families give CAFE5 enough signal to estimate the birth–death rate
and finish in seconds.

> **LF line endings are mandatory** (enforced via `.gitattributes`).
> CAFE5 does not strip a trailing CR, so a CRLF checkout makes it read
> the last species column as `D\r` and fail with "D was not found in
> gene family …".  All text fixtures here are pinned to LF.

## Used by

`tests/integration/test_full_pipeline_e2e.py::test_cafe_evolution_full_chain`.
