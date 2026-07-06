# A modern scanpy image for the scrna_seq recipe.
#
# Why not a BioContainer?  Bioconda froze the `scanpy` package at 1.7.2 (newer
# releases ship on conda-forge), so `quay.io/biocontainers/scanpy` has no image
# past 1.7.2.  We build one from conda-forge and digest-pin it in the registry
# like any other tool.  The `.github/workflows/scanpy-image.yml` workflow builds
# this, pushes it to GHCR, and repins the registry + recipe to the new digest.
#
# Verified: this image runs the scrna_seq analyze.py end-to-end (read_10x_mtx →
# filter → normalize → log1p → HVG → scale → PCA → neighbors → UMAP → leiden →
# rank_genes_groups).
FROM condaforge/miniforge3:latest

# leidenalg + python-igraph are needed for sc.tl.leiden; pin scanpy exactly so
# the built image is reproducible for a given base.
RUN mamba install -y -c conda-forge \
        "scanpy=1.12.2" leidenalg python-igraph \
    && mamba clean -afy

# Fail the build if the stack can't import (cheap smoke check).
RUN python -c "import scanpy as sc, leidenalg, igraph; print('scanpy', sc.__version__)"
