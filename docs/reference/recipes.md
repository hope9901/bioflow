# Recipes

**20 recipes**, each invokable as `bioflow recipe run <name> [options]`.  Auto-generated from the recipe registry by `scripts/gen_docs.py`.

## `amr_vf_catalogue`

ABRicate × N genomes × M databases (AMR + VF + plasmid)

*1 stage(s):*

- **abricate_one** — `staphb/abricate:1.4.0`

## `ani_matrix`

All-vs-all ANI matrix (FastANI 1.34)

*1 stage(s):*

- **fastani_all_vs_all** — `staphb/fastani:1.34`

## `atac_seq`

ATAC-seq: TrimGalore → Bowtie2 → Picard → MACS3 → TOBIAS

*5 stage(s):*

- **trim** — `quay.io/biocontainers/trim-galore:0.6.11--hdfd78af_0`
- **align** — `staphb/bowtie2:2.5.5`
- **dedup** — `quay.io/biocontainers/picard:3.4.0--hdfd78af_0`
- **call_peaks** — `quay.io/biocontainers/macs3:3.0.4--py310h5a5e57a_0`
- **footprint** — `quay.io/biocontainers/tobias:0.17.3--py39hff726c5_1`

## `cafe_evolution`

Gene family expansion/contraction (CAFE5)

*1 stage(s):*

- **run_cafe5** — `quay.io/biocontainers/cafe:5.1.0--h5ca1c30_1`

## `chip_seq`

ChIP-seq: TrimGalore → Bowtie2 → Picard → MACS3 → HOMER

*5 stage(s):*

- **trim** — `quay.io/biocontainers/trim-galore:0.6.11--hdfd78af_0`
- **align** — `staphb/bowtie2:2.5.5`
- **dedup** — `quay.io/biocontainers/picard:3.4.0--hdfd78af_0`
- **call_peaks** — `quay.io/biocontainers/macs3:3.0.4--py310h5a5e57a_0`
- **annotate_peaks** — `quay.io/biocontainers/homer:5.1--pl5321hc52dbad_1`

## `cog_enrichment`

Pangenome × COG-2024 functional-category enrichment

*2 stage(s):*

- **diamond_makedb** — `quay.io/biocontainers/diamond:2.2.2--he361c42_0`
- **diamond_blastp** — `quay.io/biocontainers/diamond:2.2.2--he361c42_0`

## `download_taxon`

Download every RefSeq assembly for a taxon (no Docker)

*0 stage(s):*


## `eukaryote_assembly`

Eukaryote long-read assembly: NanoPlot → Flye → Medaka → compleasm

*4 stage(s):*

- **read_qc** — `quay.io/biocontainers/nanoplot:1.47.1--pyhdfd78af_0`
- **assemble** — `quay.io/biocontainers/flye:2.9.6--py313h7fbb527_1`
- **polish_consensus** — `quay.io/biocontainers/medaka:2.2.2--py312h3050eb1_0`
- **assess** — `quay.io/biocontainers/compleasm:0.2.8--pyh106432d_0`

## `germline_variants`

Germline variants: fastp → BWA → GATK → bcftools → SnpEff

*6 stage(s):*

- **prepare_reference** — `quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0`
- **qc_trim** — `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0`
- **align** — `quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0`
- **call_variants** — `quay.io/biocontainers/gatk4:4.6.2.0--py310hdfd78af_1`
- **filter_variants** — `quay.io/biocontainers/bcftools:1.23.1--hb2cee57_0`
- **annotate_variants** — `quay.io/biocontainers/snpeff:5.4.0c--hdfd78af_0`

## `gwas`

Scoary GWAS over a Roary pangenome

*1 stage(s):*

- **run_scoary** — `quay.io/biocontainers/scoary:1.6.16--py_2`

## `joint_genotyping`

Cohort joint genotyping (GATK best practice): per-sample GVCF → CombineGVCFs → GenotypeGVCFs → hard-filter → SnpEff

*8 stage(s):*

- **prepare_reference** — `quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0`
- **qc_one** — `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0`
- **align_one** — `quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0`
- **call_gvcf** — `quay.io/biocontainers/gatk4:4.6.2.0--py310hdfd78af_1`
- **combine_gvcfs** — `quay.io/biocontainers/gatk4:4.6.2.0--py310hdfd78af_1`
- **genotype_cohort** — `quay.io/biocontainers/gatk4:4.6.2.0--py310hdfd78af_1`
- **hard_filter** — `quay.io/biocontainers/gatk4:4.6.2.0--py310hdfd78af_1`
- **annotate_cohort** — `quay.io/biocontainers/snpeff:5.4.0c--hdfd78af_0`

## `metagenome_assembly`

Metagenome assembly + binning: fastp → MEGAHIT → minimap2 → MetaBAT2 → CheckM2

*5 stage(s):*

- **qc_trim** — `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0`
- **assemble** — `quay.io/biocontainers/megahit:1.2.9--h2e03b76_1`
- **map_back** — `quay.io/biocontainers/mulled-v2-66534bcbb7031a148b13e2ad42583020b9cd25c4:b411340b52d82a9c276d87c7a3dcffc880be762f-0`
- **bin_genomes** — `quay.io/biocontainers/metabat2:2.18--h38e344b_2`
- **assess_bins** — `quay.io/biocontainers/checkm2:1.1.0--pyh7e72e81_1`

## `metagenomics_profile`

Shotgun metagenomic profiling: fastp → Kraken2 → Bracken → Krona

*4 stage(s):*

- **qc_trim** — `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0`
- **kraken2_classify** — `quay.io/biocontainers/kraken2:2.1.6--pl5321h077b44d_0`
- **bracken_abundance** — `quay.io/biocontainers/bracken:3.1--h9948957_0`
- **krona_chart** — `staphb/krona:2.8.1`

## `methylation_wgbs`

WGBS methylation: TrimGalore → Bismark → methylKit

*4 stage(s):*

- **bismark_prep** — `quay.io/biocontainers/bismark:0.25.1--hdfd78af_0`
- **trim** — `quay.io/biocontainers/trim-galore:0.6.11--hdfd78af_0`
- **bismark_align** — `quay.io/biocontainers/bismark:0.25.1--hdfd78af_0`
- **methylkit_dmr** — `quay.io/biocontainers/bioconductor-methylkit:1.36.0--r45ha27e39d_0`

## `pangenome`

Pangenome from a taxon: NCBI fetch → parallel Prokka → Roary

*2 stage(s):*

- **annotate** — `staphb/prokka:1.15.6`
- **run_roary** — `staphb/roary:3.13.0`

## `phylogeny`

Single-copy core gene supermatrix → MAFFT × N → IQ-TREE ML

*2 stage(s):*

- **mafft_one** — `staphb/mafft:7.526`
- **run_iqtree** — `staphb/iqtree2:2.4.0`

## `prokaryote_assembly`

Prokaryote short-read de novo assembly + Prokka annotation

*6 stage(s):*

- **qc_trim** — `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0`
- **assemble** — `staphb/spades:4.2.0`
- **annotate** — `staphb/prokka:1.15.6`
- **assembly_qc** — `staphb/quast:5.3.0`
- **genome_plot** — `staphb/genovi:0.4.3`
- **graph_image** — `staphb/bandage:0.9.0`

## `proteomics_dda`

LC-MS/MS DDA proteomics: msconvert → Comet → Percolator

*3 stage(s):*

- **msconvert** — `chambm/pwiz-skyline-i-agree-to-the-vendor-licenses:latest`
- **comet_search** — `quay.io/biocontainers/comet-ms:2026011--h9ee0642_0`
- **percolator_fdr** — `quay.io/biocontainers/percolator:3.9--h0f90025_0`

## `rnaseq_deg`

RNA-seq DEG: fastp → Salmon → DESeq2 → GO enrichment + MultiQC

*6 stage(s):*

- **multiqc_report** — `quay.io/biocontainers/multiqc:1.35--pyhdfd78af_1`
- **qc_one** — `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0`
- **salmon_index** — `quay.io/biocontainers/salmon:2.3.1--hfa8f182_0`
- **salmon_quant** — `quay.io/biocontainers/salmon:2.3.1--hfa8f182_0`
- **deseq2_diff** — `quay.io/biocontainers/bioconductor-deseq2:1.50.2--r45ha27e39d_0`
- **enrich_go** — `quay.io/biocontainers/gseapy:1.3.0--py311heb3b1e3_0`

## `scrna_seq`

scRNA-seq (10x): STARsolo + Scanpy QC/cluster/UMAP

*2 stage(s):*

- **starsolo** — `quay.io/biocontainers/star:2.7.11b--h43eeafb_0`
- **scanpy_analyze** — `ghcr.io/hope9901/bioflow-scanpy:1.12.2`

