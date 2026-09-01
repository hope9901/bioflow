# Tools

**137 tools** across 16 categories, all pulled as BioContainer / public images on first use.  This page is auto-generated from `registry/tools/` by `scripts/gen_docs.py`.

## Most-used tools · citations in 2021–2025

Ranked by how many papers cited each tool's canonical reference in the last 5 full years — a rough proxy for *current* adoption. Counts are a lower bound on real use (not everyone cites), and older tools have had longer to accrue totals. Source: Europe PMC.

| # | Tool | Category | Cites 2021–2025 | Total |
|--:|---|---|--:|--:|
| 1 | `deseq2` | deg | 53,896 | 77,941 |
| 2 | `star` | rnaseq_align | 29,725 | 44,698 |
| 3 | `starsolo` | single_cell | 29,725 | 44,698 |
| 4 | `bowtie2` | alignment | 26,180 | 46,019 |
| 5 | `mafft` | comparative_genomics | 19,719 | 33,251 |
| 6 | `edger` | deg | 19,647 | 34,777 |
| 7 | `bwa` | alignment | 18,875 | 38,853 |
| 8 | `bwa_samtools` | alignment | 18,875 | 38,853 |
| 9 | `fastp` | qc | 17,822 | 22,342 |
| 10 | `subread` | rnaseq_align | 15,970 | 22,956 |
| 11 | `bedtools` | alignment | 13,851 | 24,013 |
| 12 | `bcftools` | variant_calling | 10,774 | 13,414 |
| 13 | `samtools` | alignment | 10,774 | 13,414 |
| 14 | `minimap2` | alignment | 10,447 | 13,499 |
| 15 | `iqtree` | comparative_genomics | 10,064 | 12,634 |

> **Note:** 5 tools show `n/a` because their registry PMID points to an unrelated paper (author/year mismatch); those references are pending correction. Counts are shown only for PMIDs whose author + year match the cited work.

## alignment  (7)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bedtools` | 2.31.1 | `quay.io/biocontainers/bedtools:2.31.1--h13024bc_3` | Quinlan & Hall 2010, PMID 20110278 | 24,013 | 13,851 |
| `bowtie2` | 2.5.1 | `staphb/bowtie2:2.5.1` | Langmead & Salzberg 2012, PMID 22388286 | 46,019 | 26,180 |
| `bwa` | 0.7.19 | `quay.io/biocontainers/bwa:0.7.19--h577a1d6_1` | Li & Durbin 2009, PMID 19451168 | 38,853 | 18,875 |
| `bwa_mem2` | 2.3 | `quay.io/biocontainers/bwa-mem2:2.3--he70b90d_0` | Vasimuddin 2019, PMID 31355760 | n/a | n/a |
| `bwa_samtools` | 0.7.19 | `quay.io/biocontainers/mulled-v2-fe8faa35dbf6dc65a0f7f5d4ea12e31a79f73e40:f45ad9036aa41bb10f875a330fa877d8869018a1-0` | Li & Durbin 2009, PMID 19451168 | 38,853 | 18,875 |
| `minimap2` | 2.31 | `quay.io/biocontainers/minimap2:2.31--h118bc1c_0` | Li 2018, PMID 29750242 | 13,499 | 10,447 |
| `samtools` | 1.23.1 | `quay.io/biocontainers/samtools:1.23.1--ha83d96e_0` | Danecek 2021, PMID 33590861 | 13,414 | 10,774 |

## assembly  (16)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `abyss` | 2.3.10 | `quay.io/biocontainers/abyss:2.3.10--h4a2768f_3` | Jackman 2017, PMID 28232478 | 507 | 320 |
| `canu` | 2.3 | `quay.io/biocontainers/canu:2.3--h3fb4750_2` | Koren 2017, PMID 28298431 | 6,074 | 3,992 |
| `flye` | 2.9.6 | `quay.io/biocontainers/flye:2.9.6--py313h7fbb527_1` | Kolmogorov 2019, PMID 30936562 | 5,071 | 4,019 |
| `hifiasm` | 0.25.0 | `quay.io/biocontainers/hifiasm:0.25.0--h5ca1c30_0` | Cheng 2021, PMID 33526886 | 6,140 | 5,088 |
| `masurca` | 4.1.4 | `quay.io/biocontainers/masurca:4.1.4--ha5bb246_1` | Zimin 2017, PMID 28130360 | 367 | 224 |
| `medaka` | 2.2.2 | `quay.io/biocontainers/medaka:2.2.2--py312h3050eb1_0` | Oxford Nanopore Technologies, https://github.com/nanoporetech/medaka | n/a | n/a |
| `megahit` | 1.2.9 | `quay.io/biocontainers/megahit:1.2.9--h2e03b76_1` | Li 2015, PMID 25609793 | 7,262 | 5,398 |
| `nextdenovo` | 2.5.2 | `quay.io/biocontainers/nextdenovo:2.5.2--py311hc29ee83_7` | Hu 2024, PMID 38671502 | 412 | 308 |
| `nextpolish` | 1.4.1 | `quay.io/biocontainers/nextpolish:1.4.1--h3952c39_7` | Hu 2020, PMID 31778144 | 1,042 | 923 |
| `pilon` | 1.24 | `quay.io/biocontainers/pilon:1.24--hdfd78af_0` | Walker 2014, PMID 25409509 | 7,827 | 5,257 |
| `racon` | 1.5.0 | `quay.io/biocontainers/racon:1.5.0--h21ec9f0_2` | Vaser 2017, PMID 28100585 | 2,642 | 1,960 |
| `raven` | 1.8.3 | `quay.io/biocontainers/raven-assembler:1.8.3--h5ca1c30_3` | Vaser & Sikic 2021, PMID 38217213 | 395 | 324 |
| `shasta` | 0.14.0 | `quay.io/biocontainers/shasta:0.14.0--h9948957_0` | Shafin 2020, PMID 32686750 | 440 | 376 |
| `spades` | 4.3.0 | `staphb/spades:4.3.0` | Prjibelski 2020, PMID 32559359 | 2,798 | 2,246 |
| `unicycler` | 0.5.1 | `quay.io/biocontainers/unicycler:0.5.1--py312hdcc493e_5` | Wick 2017, PMID 28594827 | 7,344 | 5,461 |
| `verkko` | 2.3.2 | `quay.io/biocontainers/verkko:2.3.2--hb0edd9e_0` | Rautiainen 2023, PMID 36797493 | 357 | 288 |

## assembly_qc  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bandage` | 0.9.0 | `staphb/bandage:0.9.0` | Wick 2015, PMID 26099265 | 2,397 | 1,655 |
| `busco` | 6.1.0 | `quay.io/biocontainers/busco:6.1.0--pyhdfd78af_1` | Manni 2021, PMID 34320186 | 6,249 | 5,253 |
| `checkm2` | 1.1.0 | `quay.io/biocontainers/checkm2:1.1.0--pyh7e72e81_1` | Chklovski 2023, PMID 37500759 | 1,306 | 821 |
| `compleasm` | 0.2.9 | `quay.io/biocontainers/compleasm:0.2.9--pyhdfd78af_0` | Huang & Li 2023, PMID 37758247 | 318 | 219 |
| `genovi` | 0.4.3 | `staphb/genovi:0.4.3` | Cumsille et al. 2023, PMID 37014908 | 96 | 73 |
| `gfastats` | 1.3.11 | `quay.io/biocontainers/gfastats:1.3.11--h077b44d_0` | Formenti 2022, PMID 35799367 | 1,588 | 1,205 |
| `merqury` | 1.3 | `quay.io/biocontainers/merqury:1.3--hdfd78af_1` | Rhie 2020, PMID 32928274 | 4,158 | 3,400 |
| `quast` | 5.3.0 | `staphb/quast:5.3.0` | Mikheenko 2018, PMID 29949969 | 1,263 | 982 |

## comparative_genomics  (14)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `abricate` | 1.4.0 | `staphb/abricate:1.4.0` | Seemann T, ABRicate, https://github.com/tseemann/abricate | n/a | n/a |
| `cafe5` | 5.1.0 | `quay.io/biocontainers/cafe:5.1.0--h5ca1c30_1` | Mendes et al. 2021, PMID 33325497 | n/a | n/a |
| `diamond` | 2.2.2 | `quay.io/biocontainers/diamond:2.2.2--he361c42_0` | Buchfink 2021, PMID 33828273 | 4,533 | 3,563 |
| `fastani` | 1.34 | `staphb/fastani:1.34` | Jain et al. 2018, PMID 30504855 | 4,602 | 3,556 |
| `fasttree` | 2.2.0 | `quay.io/biocontainers/fasttree:2.2.0--h7b50bb2_1` | Price 2010, PMID 20224823 | 11,898 | 6,562 |
| `iqtree` | 2.4.0 | `staphb/iqtree2:2.4.0` | Minh et al. 2020, PMID 32011700 | 12,634 | 10,064 |
| `mafft` | 7.526 | `staphb/mafft:7.526` | Katoh & Standley 2013, PMID 23329690 | 33,251 | 19,719 |
| `mash` | 2.3 | `quay.io/biocontainers/mash:2.3--hb105d93_10` | Ondov 2016, PMID 27323842 | 2,670 | 1,794 |
| `muscle` | 5.3 | `quay.io/biocontainers/muscle:5.3--h9948957_3` | Edgar 2022, PMID 36379955 | 857 | 606 |
| `panaroo` | 1.8.0 | `quay.io/biocontainers/panaroo:1.8.0--pyhdfd78af_0` | Tonkin-Hill 2020, PMID 32698896 | 1,137 | 878 |
| `roary` | 3.13.0 | `staphb/roary:3.13.0` | Page et al. 2015, PMID 26198102 | 4,793 | 3,163 |
| `scoary` | 1.6.16 | `quay.io/biocontainers/scoary:1.6.16--py_2` | Brynildsrud 2016, PMID 27887642 | 594 | 412 |
| `skani` | 0.3.2 | `quay.io/biocontainers/skani:0.3.2--h79ce301_0` | Shaw & Yu 2023, PMID 37735570 | 189 | 121 |
| `trimal` | 1.5.1 | `quay.io/biocontainers/trimal:1.5.1--h9948957_0` | Capella-Gutierrez 2009, PMID 19505945 | 10,124 | 6,334 |

## deg  (3)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `deseq2` | 1.50.2 | `quay.io/biocontainers/bioconductor-deseq2:1.50.2--r45ha27e39d_0` | Love 2014, PMID 25516281 | 77,941 | 53,896 |
| `edger` | 4.8.2 | `quay.io/biocontainers/bioconductor-edger:4.8.2--r45h01b2380_0` | Robinson 2010, PMID 19910308 | 34,777 | 19,647 |
| `limma_voom` | 3.66.0 | `quay.io/biocontainers/bioconductor-limma:3.66.0--r45h01b2380_0` | Law 2014, PMID 24485249 | 5,300 | 2,986 |

## enrichment  (4)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `clusterprofiler` | 4.18.4 | `quay.io/biocontainers/bioconductor-clusterprofiler:4.18.4--r45hdfd78af_0` | Wu 2021, PMID 34557778 | 10,809 | 9,003 |
| `enrichr` | 1.3.1 | `quay.io/biocontainers/gseapy:1.3.1--py311heb3b1e3_0` | Kuleshov 2016, PMID 27141961 | 9,108 | 6,269 |
| `gseapy` | 1.3.1 | `quay.io/biocontainers/gseapy:1.3.1--py311heb3b1e3_0` | Fang 2023, PMID 36426870 | 991 | 709 |
| `topgo` | 2.62.0 | `quay.io/biocontainers/bioconductor-topgo:2.62.0--r45hdfd78af_0` | Alexa & Rahnenfuhrer 2010, https://bioconductor.org/packages/topGO/ | n/a | n/a |

## epigenomics  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bismark` | 0.25.1 | `quay.io/biocontainers/bismark:0.25.1--hdfd78af_0` | Krueger & Andrews 2011, PMID 21493656 | 4,452 | 2,506 |
| `deeptools` | 3.5.6 | `quay.io/biocontainers/deeptools:3.5.6--pyhdfd78af_0` | Ramirez et al. 2016, PMID 27079975 | 7,214 | 5,239 |
| `homer` | 5.1 | `quay.io/biocontainers/homer:5.1--pl5321hc52dbad_1` | Heinz et al. 2010, PMID 20513432 | 11,736 | 6,489 |
| `macs3` | 3.0.4 | `quay.io/biocontainers/macs3:3.0.4--py310h5a5e57a_0` | Zhang et al. 2008, PMID 18798982 | 16,061 | 8,674 |
| `methylkit` | 1.36.0 | `quay.io/biocontainers/bioconductor-methylkit:1.36.0--r45ha27e39d_0` | Akalin et al. 2012, PMID 23034086 | 1,761 | 1,035 |
| `methylpy` | 1.4.7 | `quay.io/biocontainers/methylpy:1.4.7--py39h0ae133c_0` | Schultz 2015, PMID 26030523 | 567 | 226 |
| `picard` | 3.4.0 | `quay.io/biocontainers/picard:3.4.0--hdfd78af_0` | Broad Institute, https://broadinstitute.github.io/picard/ | n/a | n/a |
| `tobias` | 0.17.3 | `quay.io/biocontainers/tobias:0.17.3--py39hff726c5_1` | Bentsen et al. 2020, PMID 32848148 | 638 | 540 |

## func_annot  (10)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `antismash` | 8.0.4 | `antismash/standalone:8.0.4` | Blin 2023, PMID 37140036 | 1,784 | 1,441 |
| `dbcan` | 5.2.9 | `quay.io/biocontainers/dbcan:5.2.9--pyhdfd78af_0` | Zhang 2018, PMID 29771380 | 1,781 | 1,385 |
| `dram` | 1.5.0 | `quay.io/biocontainers/dram:1.5.0--pyhdfd78af_0` | Shaffer 2020, PMID 32766782 | 957 | 791 |
| `eggnog_mapper` | 2.1.15 | `quay.io/biocontainers/eggnog-mapper:2.1.15--pyhdfd78af_0` | Cantalapiedra 2021, PMID 34597405 | 3,843 | 2,967 |
| `funannotate` | 1.8.17 | `quay.io/biocontainers/funannotate:1.8.17--pyhdfd78af_5` | Palmer & Stajich 2020, funannotate (Zenodo) | n/a | n/a |
| `gecco` | 0.10.3 | `quay.io/biocontainers/gecco:0.10.3--pyhdfd78af_1` | Larralde 2021, GECCO (bioRxiv 10.1101/2021.05.03.442509) | n/a | n/a |
| `gtdbtk` | 2.7.2 | `quay.io/biocontainers/gtdbtk:2.7.2--pyhdfd78af_0` | Chaumeil 2022, PMID 36218463 | 1,724 | 1,254 |
| `interproscan` | 5.59_91.0 | `quay.io/biocontainers/interproscan:5.59_91.0--hec16e2b_1` | Blum 2021, PMID 33156333 | 1,825 | 1,687 |
| `kofamscan` | 1.3.0 | `quay.io/biocontainers/kofamscan:1.3.0--hdfd78af_2` | Aramaki 2020, PMID 31742321 | 1,559 | 1,265 |
| `pfam_scan` | 1.6 | `quay.io/biocontainers/pfam_scan:1.6--hdfd78af_5` | Mistry 2021, PMID 33125078 | 5,247 | 4,614 |

## metagenomics  (10)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bracken` | 3.1 | `quay.io/biocontainers/bracken:3.1--h9948957_0` | Lu et al. 2017, PMID 28655956 | n/a | n/a |
| `humann3` | 3.9 | `quay.io/biocontainers/humann:3.9--py312hdfd78af_0` | Beghini et al. 2021, PMID 33944776 | 1,914 | 1,590 |
| `kneaddata` | 0.12.4 | `quay.io/biocontainers/kneaddata:0.12.4--pyhdfd78af_0` | McIver et al. 2018, PMID 31616210 | n/a | n/a |
| `kraken2` | 2.17.1 | `quay.io/biocontainers/kraken2:2.17.1--pl5321h077b44d_0` | Wood et al. 2019, PMID 31779668 | 5,584 | 4,456 |
| `krona` | 2.8.1 | `staphb/krona:2.8.1` | Ondov 2011, PMID 21961884 | 1,462 | 785 |
| `lefse` | 1.1.2 | `quay.io/biocontainers/lefse:1.1.2--pyhdfd78af_0` | Segata et al. 2011, PMID 21702898 | 12,010 | 7,555 |
| `maxbin2` | 2.2.7 | `quay.io/biocontainers/maxbin2:2.2.7--h503566f_8` | Wu 2016, PMID 26515820 | 2,252 | 1,640 |
| `metabat2` | 2.18 | `quay.io/biocontainers/metabat2:2.18--h38e344b_2` | Kang 2019, PMID 31388474 | 3,168 | 2,585 |
| `metaphlan4` | 4.2.4 | `quay.io/biocontainers/metaphlan:4.2.4--pyhdfd78af_0` | Blanco-Miguez et al. 2023, PMID 36823356 | 1,210 | 869 |
| `sourmash` | 4.9.4 | `quay.io/biocontainers/sourmash:4.9.4--hdfd78af_0` | Brown & Irber 2016, sourmash (JOSS 10.21105/joss.00027) | n/a | n/a |

## proteomics  (9)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `comet` | 2026.01.1 | `quay.io/biocontainers/comet-ms:2026011--h9ee0642_0` | Eng 2013, PMID 23148064 | 1,344 | 753 |
| `fragpipe` ⚠️ deprecated | 22.0 | `fcyu/fragpipe:22.0` | Yu et al. 2020, PMID 33338430 | n/a | n/a |
| `maxquant` ⚠️ deprecated | 2.4.14.0 | `quay.io/biocontainers/maxquant:2.4.14.0--hdfd78af_0` | Cox & Mann 2008, PMID 19029910 | 13,144 | 5,790 |
| `msconvert` | 3.0.24238 | `chambm/pwiz-skyline-i-agree-to-the-vendor-licenses:latest` | Chambers et al. 2012, PMID 23051804 | 3,410 | 2,121 |
| `msfragger` ⚠️ deprecated | 4.1 | `fcyu/msfragger:4.1` | Kong et al. 2017, PMID 28394336 | 2,226 | 1,694 |
| `msgf_plus` | 2024.03.26 | `quay.io/biocontainers/msgf_plus:2024.03.26--hdfd78af_0` | Kim 2014, PMID 25358478 | 932 | 458 |
| `openms` | 3.5.0 | `quay.io/biocontainers/openms:3.5.0--h78fb946_0` | Rost 2016, PMID 27575624 | 536 | 329 |
| `percolator` | 3.9 | `quay.io/biocontainers/percolator:3.9--h0f90025_0` | Kall et al. 2007, PMID 17952086 | 2,062 | 953 |
| `xtandem` | 15.12.15.2 | `quay.io/biocontainers/xtandem:15.12.15.2--h4464bbb_11` | Craig & Beavis 2004, PMID 14976030 | 1,973 | 330 |

## qc  (9)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `cutadapt` | 5.2 | `quay.io/biocontainers/cutadapt:5.2--py312hfabe715_2` | Martin 2011, doi:10.14806/ej.17.1.200 | n/a | n/a |
| `fastp` | 1.3.6 | `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0` | Chen 2018, PMID 30423086 | 22,342 | 17,822 |
| `fastqc` | 0.12.1 | `quay.io/biocontainers/fastqc:0.12.1--hdfd78af_0` | Andrews S, 2010 (Babraham Bioinformatics) | n/a | n/a |
| `filtlong` | 0.3.1 | `quay.io/biocontainers/filtlong:0.3.1--h077b44d_0` | Wick 2021 (github.com/rrwick/Filtlong) | n/a | n/a |
| `multiqc` | 1.35 | `quay.io/biocontainers/multiqc:1.35--pyhdfd78af_1` | Ewels 2016, PMID 27312411 | 8,782 | 6,639 |
| `nanoplot` | 1.47.1 | `quay.io/biocontainers/nanoplot:1.47.1--pyhdfd78af_0` | De Coster 2023, PMID 37171891 | 707 | 471 |
| `seqkit` | 2.13.0 | `quay.io/biocontainers/seqkit:2.13.0--he881be0_0` | Shen 2016, PMID 27706213 | 2,797 | 2,241 |
| `seqtk` | r93 | `quay.io/biocontainers/seqtk:r93--0` | Li, seqtk (github.com/lh3/seqtk) | n/a | n/a |
| `trimgalore` | 0.6.11 | `quay.io/biocontainers/trim-galore:0.6.11--hdfd78af_0` | Krueger 2015, https://github.com/FelixKrueger/TrimGalore | n/a | n/a |

## repeat  (3)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `earlgrey` | 7.2.6 | `quay.io/biocontainers/earlgrey:7.2.6--hc52dbad_0` | Baril 2024, PMID 38577785 | 209 | 135 |
| `repeatmasker` | 4.1.7 | `dfam/tetools:1.89` | Smit 2015 (repeatmasker.org) | n/a | n/a |
| `repeatmodeler` | 2.0.5 | `dfam/tetools:1.89` | Flynn 2020, PMID 32300014 | 3,388 | 2,836 |

## rnaseq_align  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `hisat2` | 2.2.2 | `quay.io/biocontainers/hisat2:2.2.2--h503566f_0` | Kim 2019, PMID 31375807 | 12,110 | 9,933 |
| `htseq` | 2.1.2 | `quay.io/biocontainers/htseq:2.1.2--py311h483b626_2` | Anders 2015, PMID 25260700 | 17,682 | 9,414 |
| `kallisto` | 0.52.0 | `quay.io/biocontainers/kallisto:0.52.0--h13ff97a_0` | Bray 2016, PMID 27043002 | 8,295 | 5,420 |
| `rsem` | 1.3.3 | `quay.io/biocontainers/rsem:1.3.3--pl5321h077b44d_12` | Li & Dewey 2011, PMID 21816040 | 17,224 | 9,740 |
| `salmon` | 2.4.1 | `quay.io/biocontainers/salmon:2.4.1--hfa8f182_0` | Patro 2017, PMID 28263959 | 10,538 | 7,715 |
| `star` | 2.7.11b | `quay.io/biocontainers/star:2.7.11b--h43eeafb_0` | Dobin 2013, PMID 23104886 | 44,698 | 29,725 |
| `stringtie` | 3.0.3 | `quay.io/biocontainers/stringtie:3.0.3--h29c0135_0` | Pertea 2015, PMID 25690850 | 10,933 | 7,924 |
| `subread` | 2.1.1 | `quay.io/biocontainers/subread:2.1.1--h577a1d6_0` | Liao 2014, PMID 24227677 | 22,956 | 15,970 |

## single_cell  (9)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bustools` | 0.45.1 | `quay.io/biocontainers/bustools:0.45.1--h6f0a7f7_0` | Melsted 2019, PMID 31073610 | 129 | 111 |
| `cellranger` | 9.0.1 | `litd/docker-cellranger:v9.0.1` | Zheng et al. 2017, PMID 28091601 | 6,154 | 4,200 |
| `harmony` | 2.0.0 | `quay.io/biocontainers/harmonypy:2.0.0--py310hd766df8_1` | Korsunsky 2019, PMID 31740819 | 8,812 | 6,907 |
| `kb_python` | 0.28.2 | `quay.io/biocontainers/kb-python:0.28.2--pyhdfd78af_2` | Melsted 2021, PMID 33795888 | 346 | 316 |
| `monocle3` | 1.4.26 | `quay.io/biocontainers/r-monocle3:1.4.26--r44h9948957_0` | Cao et al. 2019, PMID 30787392 | 447 | 381 |
| `scanpy` | 1.12.2 | `ghcr.io/hope9901/bioflow-scanpy:1.12.2` | Wolf et al. 2018, PMID 29409532 | 7,536 | 5,778 |
| `scrublet` | 0.2.3 | `quay.io/biocontainers/scrublet:0.2.3--pyh5e36f6f_1` | Wolock 2019, PMID 30954476 | 2,430 | 1,911 |
| `seurat` | 5.5.1 | `satijalab/seurat:5.5.1` | Hao et al. 2024, PMID 37231261 | 4,647 | 2,979 |
| `starsolo` | 2.7.11b | `quay.io/biocontainers/star:2.7.11b--h43eeafb_0` | Dobin et al. 2013, PMID 23104886 | 44,698 | 29,725 |

## struct_annot  (10)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `augustus` | 3.5.0 | `quay.io/biocontainers/augustus:3.5.0--pl5321h9716f88_9` | Stanke 2008, PMID 18218656 | 2,111 | 1,293 |
| `bakta` | 1.12.0 | `quay.io/biocontainers/bakta:1.12.0--pyhdfd78af_0` | Schwengers 2021, PMID 34739369 | 1,178 | 814 |
| `braker3` | 3.1.1 | `teambraker/braker3:v3.1.1` | Gabriel 2024, PMID 38866550 | 622 | 387 |
| `dfast` | 1.4.1 | `quay.io/biocontainers/dfast:1.4.1--h7f5d12c_0` | Tanizawa 2018, PMID 29106469 | 1,076 | 773 |
| `glimmerhmm` | 3.0.4 | `quay.io/biocontainers/glimmerhmm:3.0.4--pl5321h503566f_10` | Majoros 2004, PMID 15145805 | 1,566 | 975 |
| `liftoff` | 1.6.3 | `quay.io/biocontainers/liftoff:1.6.3--pyhdfd78af_0` | Shumate & Salzberg 2021, PMID 33320174 | 842 | 688 |
| `prodigal` | 2.6.3 | `quay.io/biocontainers/prodigal:2.6.3--h577a1d6_11` | Hyatt 2010, PMID 20211023 | 9,890 | 5,658 |
| `prokka` | 1.14.6 | `staphb/prokka:1.14.6` | Seemann 2014, PMID 24642063 | 15,509 | 9,935 |
| `snap` | 2017-03-01 | `quay.io/biocontainers/snap:2017_03_01--h7b50bb2_0` | Korf 2004, PMID 15144565 | 2,654 | 1,469 |
| `trnascan_se` | 2.0.13 | `quay.io/biocontainers/trnascan-se:2.0.13--pl5321hab16a5f_0` | Chan 2021, PMID 34417604 | 1,575 | 1,247 |

## variant_calling  (9)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bcftools` | 1.24 | `quay.io/biocontainers/bcftools:1.24--h487d631_1` | Danecek 2021, PMID 33590861 | 13,414 | 10,774 |
| `deepvariant` | 1.10.0 | `google/deepvariant:1.10.0` | Poplin 2018, PMID 30247488 | 1,333 | 998 |
| `delly` | 2.5.1 | `quay.io/biocontainers/delly:2.5.1--h3752d28_0` | Rausch 2012, PMID 22962449 | 2,009 | 1,108 |
| `ensembl_vep` | 116.0 | `quay.io/biocontainers/ensembl-vep:116.0--pl5321h2a3209d_0` | McLaren 2016, PMID 27268795 | 6,703 | 4,575 |
| `freebayes` | 1.3.10 | `quay.io/biocontainers/freebayes:1.3.10--hbefcdb2_0` | Garrison & Marth 2012, arXiv:1207.3907 | n/a | n/a |
| `gatk4` | 4.6.2.0 | `quay.io/biocontainers/gatk4:4.6.2.0--py310hdfd78af_1` | McKenna 2010, PMID 20644199 | 17,362 | 8,152 |
| `glnexus` | 1.4.1 | `quay.io/biocontainers/glnexus:1.4.1--h40d77a6_0` | Yun 2021, PMID 33399819 | 215 | 169 |
| `snpeff` | 5.4.0c | `quay.io/biocontainers/snpeff:5.4.0c--hdfd78af_0` | Cingolani 2012, PMID 22728672 | 9,873 | 5,511 |
| `vcftools` | 0.1.17 | `quay.io/biocontainers/vcftools:0.1.17--pl5321h077b44d_0` | Danecek 2011, PMID 21653522 | 12,684 | 7,596 |

