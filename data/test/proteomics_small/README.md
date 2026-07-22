# proteomics_small — synthetic DDA MS/MS fixture

A tiny synthetic proteomics fixture for exercising the `proteomics_dda` recipe's
search + FDR stages (both `search=comet` and `--set search=msgf`) without real
mass-spec data.

- `spectra.mgf` — 3 MS2 spectra, each the exact theoretical b/y-ion ladder
  (monoisotopic, charge 2+) of a tryptic peptide: `LGGNEQVTR`, `YILAGVENSK`,
  `GTFIIDPGGVIR` (iRT peptides).
- `target.fasta` — one target protein containing those three peptides flanked by
  K/R. **Target-only**: both engines make their own decoys (Comet
  `decoy_search=1`, MS-GF+ `-tda 1`).
- `comet.params` — a tuned Comet parameter file (20 ppm precursor, high-res
  fragments). The recipe forces `decoy_search=1` + `output_percolatorfile=1` on
  top of whatever is passed.

Because the spectra are exact theoretical matches, both engines identify all
three peptides confidently: Comet e-values 1e-9…1e-16 (writes a Percolator
`.pin`); MS-GF+ QValue 0.0 (`MzIDToTsv` → the QValue filter yields a 3-PSM
`passing_psms.tsv`). The FDR *tail* (Percolator's semi-supervised rescaling)
needs realistic PSM counts, so it isn't driven to completion on 3 spectra.
