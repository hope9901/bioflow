# Recipes

**19 recipes**, each invokable as `bioflow recipe run <name> [options]`.  Auto-generated from the recipe registry by `scripts/gen_docs.py`.

## `amr_vf_catalogue`

ABRicate × N genomes × M databases (AMR + VF + plasmid)

*1 stage(s):*

- **abricate_one** — `staphb/abricate:1.2.0`

## `ani_matrix`

All-vs-all ANI matrix (FastANI 1.34)

*1 stage(s):*

- **fastani_all_vs_all** — `staphb/fastani:1.34`

## `atac_seq`

ATAC-seq: TrimGalore → Bowtie2 → Picard → MACS3 → TOBIAS

*5 stage(s):*

- **trim** — `quay.io/biocontainers/trim-galore:0.6.10--hdfd78af_0`
- **align** — `quay.io/biocontainers/bowtie2:2.5.4--py39h6fed5c7_0`
- **dedup** — `quay.io/biocontainers/picard:3.2.0--hdfd78af_0`
- **call_peaks** — `quay.io/biocontainers/macs3:3.0.1--py310h58a0a2b_1`
- **footprint** — `quay.io/biocontainers/tobias:0.16.1--py310h590aeec_0`

## `cafe_evolution`

Gene family expansion/contraction (CAFE5)

*1 stage(s):*

- **run_cafe5** — `quay.io/biocontainers/cafe:5.1.0--h5ca1c30_1`

## `chip_seq`

ChIP-seq: TrimGalore → Bowtie2 → Picard → MACS3 → HOMER

*5 stage(s):*

- **trim** — `quay.io/biocontainers/trim-galore:0.6.10--hdfd78af_0`
- **align** — `quay.io/biocontainers/bowtie2:2.5.4--py39h6fed5c7_0`
- **dedup** — `quay.io/biocontainers/picard:3.2.0--hdfd78af_0`
- **call_peaks** — `quay.io/biocontainers/macs3:3.0.1--py310h58a0a2b_1`
- **annotate_peaks** — `quay.io/biocontainers/homer:4.11.1--pl5321h9f5acd7_7`

## `cog_enrichment`

Pangenome × COG-2024 functional-category enrichment

*2 stage(s):*

- **diamond_makedb** — `quay.io/biocontainers/diamond:2.1.8--h43eeafb_0`
- **diamond_blastp** — `quay.io/biocontainers/diamond:2.1.8--h43eeafb_0`

## `download_taxon`

Download every RefSeq assembly for a taxon (no Docker)

*0 stage(s):*


## `eukaryote_assembly`

Eukaryote long-read assembly: NanoPlot → Flye → Medaka → compleasm

*4 stage(s):*

- **read_qc** — `quay.io/biocontainers/nanoplot:1.43.0--pyhdfd78af_0`
- **assemble** — `quay.io/biocontainers/flye:2.9.5--py39h3d6084e_1`
- **polish** — `quay.io/biocontainers/medaka:1.11.3--py39h05d5c5e_2`
- **assess** — `quay.io/biocontainers/compleasm:0.2.6--pyh7cba7a3_0`

## `germline_variants`

Germline variants: fastp → BWA → GATK → bcftools → SnpEff

*5 stage(s):*

- **qc_trim** — `quay.io/biocontainers/fastp:0.23.4--h5f740d0_0`
- **align** — `quay.io/biocontainers/bwa:0.7.18--he4a0461_0`
- **call_variants** — `quay.io/biocontainers/gatk4:4.6.1.0--py310hdfd78af_0`
- **filter_variants** — `quay.io/biocontainers/bcftools:1.21--h8b25389_0`
- **annotate_variants** — `quay.io/biocontainers/snpeff:5.2--hdfd78af_1`

## `gwas`

Scoary GWAS over a Roary pangenome

*1 stage(s):*

- **run_scoary** — `quay.io/biocontainers/scoary:1.6.16--py_2`

## `metagenome_assembly`

Metagenome assembly + binning: fastp → MEGAHIT → minimap2 → MetaBAT2 → CheckM2

*5 stage(s):*

- **qc_trim** — `quay.io/biocontainers/fastp:0.23.4--h5f740d0_0`
- **assemble** — `quay.io/biocontainers/megahit:1.2.9--h2e03b76_1`
- **map_back** — `quay.io/biocontainers/minimap2:2.28--he4a0461_0`
- **bin_genomes** — `quay.io/biocontainers/metabat2:2.17--h4da6f23_2`
- **assess_bins** — `quay.io/biocontainers/checkm2:1.0.2--pyh7cba7a3_0`

## `metagenomics_profile`

Shotgun metagenomic profiling: fastp → Kraken2 → Bracken

*3 stage(s):*

- **qc_trim** — `quay.io/biocontainers/fastp:0.23.4--h5f740d0_0`
- **kraken2_classify** — `quay.io/biocontainers/kraken2:2.1.3--pl5321hdcf5f25_0`
- **bracken_abundance** — `quay.io/biocontainers/bracken:2.9--py39h7cff6ad_0`

## `methylation_wgbs`

WGBS methylation: TrimGalore → Bismark → methylKit

*3 stage(s):*

- **trim** — `quay.io/biocontainers/trim-galore:0.6.10--hdfd78af_0`
- **bismark_align** — `quay.io/biocontainers/bismark:0.24.2--hdfd78af_0`
- **methylkit_dmr** — `bioconductor/bioconductor_full:RELEASE_3_18`

## `pangenome`

Pangenome from a taxon: NCBI fetch → parallel Prokka → Roary

*2 stage(s):*

- **annotate** — `staphb/prokka:1.14.6`
- **run_roary** — `staphb/roary:3.13.0`

## `phylogeny`

Single-copy core gene supermatrix → MAFFT × N → IQ-TREE ML

*2 stage(s):*

- **mafft_one** — `staphb/mafft:7.520`
- **run_iqtree** — `staphb/iqtree2:2.2.2.7`

## `prokaryote_assembly`

Prokaryote short-read de novo assembly + Prokka annotation

*4 stage(s):*

- **qc_trim** — `quay.io/biocontainers/fastp:0.23.4--h5f740d0_0`
- **assemble** — `staphb/spades:4.0.0`
- **annotate** — `staphb/prokka:1.14.6`
- **assembly_qc** — `staphb/quast:5.2.0`

## `proteomics_dda`

LC-MS/MS DDA proteomics: msconvert → Comet → Percolator

*3 stage(s):*

- **msconvert** — `chambm/pwiz-skyline-i-agree-to-the-vendor-licenses:latest`
- **comet_search** — `quay.io/biocontainers/comet-ms:2024020--h7ec2334_0`
- **percolator_fdr** — `quay.io/biocontainers/percolator:3.06.1--hf1761c0_2`

## `rnaseq_deg`

RNA-seq DEG: fastp → Salmon → DESeq2

*4 stage(s):*

- **qc_one** — `quay.io/biocontainers/fastp:0.23.4--h5f740d0_0`
- **salmon_index** — `quay.io/biocontainers/salmon:1.10.3--hb950928_0`
- **salmon_quant** — `quay.io/biocontainers/salmon:1.10.3--hb950928_0`
- **deseq2_diff** — `quay.io/biocontainers/bioconductor-deseq2:1.44.0--r43hf17093f_0`

## `scrna_seq`

scRNA-seq (10x): STARsolo + Scanpy QC/cluster/UMAP

*2 stage(s):*

- **starsolo** — `quay.io/biocontainers/star:2.7.11b--h43eeafb_0`
- **scanpy_analyze** — `quay.io/biocontainers/scanpy:1.10.1--pyhdfd78af_0`

