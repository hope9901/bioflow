---
title: 'bioflow: reproducible, one-line bioinformatics over digest-pinned container recipes'
tags:
  - bioinformatics
  - reproducibility
  - provenance
  - workflows
  - containers
  - Python
authors:
  # TODO: replace with the real author name(s), ORCID and affiliation before
  # submitting to JOSS.
  - name: hope9901
    orcid: 0000-0000-0000-0000
    affiliation: 1
affiliations:
  - name: Independent researcher
    index: 1
date: 3 July 2026
bibliography: paper.bib
---

# Summary

`bioflow` (distributed on PyPI as `bioflowkit`) is an open-source Python SDK and
cookbook that runs common bioinformatics analyses as one command each, while
making every run reproducible and auditable by construction. Each analysis step
executes inside its own pinned BioContainer [@daSilva2017biocontainers] as a
sibling Docker (or Apptainer/Singularity) container over a shared workspace, so
nothing but Docker and Python is installed on the host. A curated registry of
113 tools — every image pinned by content digest — backs 20 end-to-end recipes
spanning genome assembly, variant calling, RNA-seq, metagenomics, single-cell,
epigenomics and comparative genomics. Every run records the input SHA-256
hashes, image digests, commands and timestamps as a machine-readable research
object (RO-Crate [@soilandreyes2022rocrate] / PROV-O), and emits a tidy,
analysis-ready results table plus an at-a-glance HTML overview that surfaces the
field-standard tools' own reports rather than re-drawing them.

# Statement of need

Reproducing a published bioinformatics analysis is often difficult: pipelines
depend on many tools whose versions drift, container tags are silently
re-pushed, and the exact commands and inputs are rarely captured alongside the
results [@gruning2018bioconda]. Established workflow managers such as Snakemake
[@molder2021snakemake] and Nextflow [@ditommaso2017nextflow] provide the
execution substrate for scalable pipelines, but leave the choice, pinning and
provenance of the underlying tools to the author, and carry a learning curve
that is a barrier for researchers who simply want to run a standard analysis
once, correctly.

`bioflow` targets that gap with a reproducibility-first, low-ceremony design:

- **Digest-pinned by default.** Every tool image is referenced by its content
  digest, so a re-tagged upstream image cannot change a result; a CI audit
  blocks any un-pinned active tool from shipping.
- **One line per analysis.** Curated recipes (`bioflow recipe run
  prokaryote_assembly …`) orchestrate multi-tool pipelines without writing a
  workflow, while an `@stage`/`@pipeline` Python SDK is available for custom
  pipelines.
- **Provenance and caching for free.** Each run writes `provenance.json` and
  `ro-crate-metadata.json`; unchanged inputs hit a content-addressed cache.
- **Honest visualization.** bioflow hands over tidy per-sample tables and an
  overview that embeds or links each tool's own output (e.g. QUAST, a GenoVi
  circular genome map [@cumsille2023genovi], Krona [@ondov2011krona]), rather
  than maintaining a bespoke plotting layer.
- **Runs anywhere.** The same recipes run on a workstation with Docker or an HPC
  cluster with Apptainer/Singularity [@kurtzer2017singularity]; Podman and GPU
  pass-through are supported.

By combining a curated, digest-pinned tool registry with one-command recipes and
built-in provenance, `bioflow` lowers the effort of running a *correct,
re-runnable* analysis, and makes the resulting research object easy to archive,
audit and cite.

# Acknowledgements

`bioflow` builds on the BioContainers community and the many open-source tools
in its registry, each cited in the tool reference documentation.

# References
