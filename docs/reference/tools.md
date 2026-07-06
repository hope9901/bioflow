# Tools

**113 tools** across 16 categories, all pulled as BioContainer / public images on first use.  This page is auto-generated from `registry/tools/` by `scripts/gen_docs.py`.

## Most-used tools · citations in 2021–2025

Ranked by how many papers cited each tool's canonical reference in the last 5 full years — a rough proxy for *current* adoption. Counts are a lower bound on real use (not everyone cites), and older tools have had longer to accrue totals. Source: Europe PMC.

| # | Tool | Category | Cites 2021–2025 | Total |
|--:|---|---|--:|--:|
| 1 | `deseq2` | deg | 52,540 | 72,197 |
| 2 | `star` | rnaseq_align | 29,078 | 41,990 |
| 3 | `starsolo` | single_cell | 29,078 | 41,990 |
| 4 | `bowtie2` | alignment | 25,521 | 43,646 |
| 5 | `mafft` | comparative_genomics | 19,262 | 31,071 |
| 6 | `edger` | deg | 19,177 | 33,219 |
| 7 | `bwa` | alignment | 18,313 | 36,991 |
| 8 | `fastp` | qc | 17,361 | 19,916 |
| 9 | `subread` | rnaseq_align | 15,592 | 21,327 |
| 10 | `bedtools` | alignment | 13,559 | 22,804 |
| 11 | `bcftools` | variant_calling | 10,492 | 11,759 |
| 12 | `samtools` | alignment | 10,492 | 11,759 |
| 13 | `minimap2` | alignment | 10,215 | 12,265 |
| 14 | `iqtree` | comparative_genomics | 9,802 | 11,112 |
| 15 | `prokka` | struct_annot | 9,722 | 14,442 |

> **Note:** 5 tools show `n/a` because their registry PMID points to an unrelated paper (author/year mismatch); those references are pending correction. Counts are shown only for PMIDs whose author + year match the cited work.

## alignment  (6)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bedtools` | 2.31.1 | `quay.io/biocontainers/bedtools:2.31.1--h13024bc_3` | Quinlan & Hall 2010, PMID 20110278 | 22,804 | 13,559 |
| `bowtie2` | 2.5.4 | `staphb/bowtie2:2.5.4` | Langmead & Salzberg 2012, PMID 22388286 | 43,646 | 25,521 |
| `bwa` | 0.7.18 | `quay.io/biocontainers/bwa:0.7.18--he4a0461_0` | Li & Durbin 2009, PMID 19451168 | 36,991 | 18,313 |
| `bwa_mem2` | 2.2.1 | `quay.io/biocontainers/bwa-mem2:2.2.1--he513fc3_0` | Vasimuddin 2019, PMID 31355760 | n/a | n/a |
| `minimap2` | 2.28 | `quay.io/biocontainers/minimap2:2.28--he4a0461_0` | Li 2018, PMID 29750242 | 12,265 | 10,215 |
| `samtools` | 1.20 | `quay.io/biocontainers/samtools:1.20--h50ea8bc_0` | Danecek 2021, PMID 33590861 | 11,759 | 10,492 |

## assembly  (16)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `abyss` | 2.3.7 | `quay.io/biocontainers/abyss:2.3.7--h103dbdd_4` | Jackman 2017, PMID 28232478 | 477 | 311 |
| `canu` | 2.2 | `quay.io/biocontainers/canu:2.2--ha47f30e_0` | Koren 2017, PMID 28298431 | 5,808 | 3,918 |
| `flye` | 2.9.5 | `quay.io/biocontainers/flye:2.9.5--py310h275bdba_2` | Kolmogorov 2019, PMID 30936562 | 4,601 | 3,951 |
| `hifiasm` | 0.19.9 | `quay.io/biocontainers/hifiasm:0.19.9--h43eeafb_0` | Cheng 2021, PMID 33526886 | 5,591 | 5,013 |
| `masurca` | 4.1.0 | `quay.io/biocontainers/masurca:4.1.0--pl5321hb5bd705_1` | Zimin 2017, PMID 28130360 | 363 | 224 |
| `medaka` | 1.11.3 | `quay.io/biocontainers/medaka:1.11.3--py39h05d5c5e_0` | Oxford Nanopore Technologies, https://github.com/nanoporetech/medaka | n/a | n/a |
| `megahit` | 1.2.9 | `quay.io/biocontainers/megahit:1.2.9--h2e03b76_1` | Li 2015, PMID 25609793 | 6,572 | 5,226 |
| `nextdenovo` | 2.5.2 | `quay.io/biocontainers/nextdenovo:2.5.2--py311hc29ee83_7` | Hu 2024, PMID 38671502 | 364 | 303 |
| `nextpolish` | 1.4.1 | `quay.io/biocontainers/nextpolish:1.4.1--h3952c39_7` | Hu 2020, PMID 31778144 | 979 | 912 |
| `pilon` | 1.24 | `quay.io/biocontainers/pilon:1.24--hdfd78af_0` | Walker 2014, PMID 25409509 | 7,420 | 5,166 |
| `racon` | 1.5.0 | `quay.io/biocontainers/racon:1.5.0--h21ec9f0_2` | Vaser 2017, PMID 28100585 | 2,476 | 1,921 |
| `raven` | 1.8.1 | `quay.io/biocontainers/raven-assembler:1.8.1--h43eeafb_3` | Vaser & Sikic 2021, PMID 38217213 | 360 | 317 |
| `shasta` | 0.11.1 | `quay.io/biocontainers/shasta:0.11.1--h4ac6f70_2` | Shafin 2020, PMID 32686750 | 424 | 370 |
| `spades` | 4.0.0 | `staphb/spades:4.0.0` | Prjibelski 2020, PMID 32559359 | 2,447 | 2,199 |
| `unicycler` | 0.5.1 | `quay.io/biocontainers/unicycler:0.5.1--py312hdcc493e_5` | Wick 2017, PMID 28594827 | 6,765 | 5,353 |
| `verkko` | 2.2.1 | `quay.io/biocontainers/verkko:2.2.1--h45dadce_0` | Rautiainen 2023, PMID 36797493 | 302 | 275 |

## assembly_qc  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bandage` | 0.8.1 | `staphb/bandage:0.8.1` | Wick 2015, PMID 26099265 | 2,190 | 1,623 |
| `busco` | 5.7.1 | `quay.io/biocontainers/busco:5.7.1--pyhdfd78af_0` | Manni 2021, PMID 34320186 | 5,713 | 5,173 |
| `checkm2` | 1.0.2 | `quay.io/biocontainers/checkm2:1.0.2--pyh7cba7a3_0` | Chklovski 2023, PMID 37500759 | 1,011 | 783 |
| `compleasm` | 0.2.6 | `quay.io/biocontainers/compleasm:0.2.6--pyh7cba7a3_0` | Huang & Li 2023, PMID 37758247 | 260 | 210 |
| `genovi` | 0.4.3 | `staphb/genovi:0.4.3` | Cumsille et al. 2023, PMID 37014908 | 80 | 71 |
| `gfastats` | 1.3.7 | `quay.io/biocontainers/gfastats:1.3.7--hdcf5f25_1` | Formenti 2022, PMID 35799367 | 1,395 | 1,188 |
| `merqury` | 1.3 | `quay.io/biocontainers/merqury:1.3--hdfd78af_1` | Rhie 2020, PMID 32928274 | 3,771 | 3,358 |
| `quast` | 5.2.0 | `staphb/quast:5.2.0` | Mikheenko 2018, PMID 29949969 | 1,175 | 969 |

## comparative_genomics  (11)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `abricate` | 1.2.0 | `staphb/abricate:1.2.0` | Seemann T, ABRicate, https://github.com/tseemann/abricate | n/a | n/a |
| `cafe5` | 5.1.0 | `quay.io/biocontainers/cafe:5.1.0--h5ca1c30_1` | Mendes et al. 2021, PMID 33325497 | n/a | n/a |
| `diamond` | 2.1.8 | `quay.io/biocontainers/diamond:2.1.8--h43eeafb_0` | Buchfink 2021, PMID 33828273 | 3,993 | 3,476 |
| `fastani` | 1.34 | `staphb/fastani:1.34` | Jain et al. 2018, PMID 30504855 | 4,164 | 3,481 |
| `iqtree` | 2.2.6 | `staphb/iqtree2:2.2.2.7` | Minh et al. 2020, PMID 32011700 | 11,112 | 9,802 |
| `mafft` | 7.520 | `staphb/mafft:7.520` | Katoh & Standley 2013, PMID 23329690 | 31,071 | 19,262 |
| `mash` | 2.3 | `quay.io/biocontainers/mash:2.3--hb105d93_10` | Ondov 2016, PMID 27323842 | 2,452 | 1,753 |
| `panaroo` | 1.8.0 | `quay.io/biocontainers/panaroo:1.8.0--pyhdfd78af_0` | Tonkin-Hill 2020, PMID 32698896 | 980 | 857 |
| `roary` | 3.13.0 | `staphb/roary:3.13.0` | Page et al. 2015, PMID 26198102 | 4,460 | 3,099 |
| `scoary` | 1.6.16 | `quay.io/biocontainers/scoary:1.6.16--py_2` | Brynildsrud 2016, PMID 27887642 | 564 | 405 |
| `skani` | 0.2.2 | `quay.io/biocontainers/skani:0.2.2--ha6fb395_2` | Shaw & Yu 2023, PMID 37735570 | 134 | 111 |

## deg  (3)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `deseq2` | 1.44.0 | `quay.io/biocontainers/bioconductor-deseq2:1.50.2--r45ha27e39d_0` | Love 2014, PMID 25516281 | 72,197 | 52,540 |
| `edger` | 4.2.0 | `quay.io/biocontainers/bioconductor-edger:4.8.2--r45h01b2380_0` | Robinson 2010, PMID 19910308 | 33,219 | 19,177 |
| `limma_voom` | 3.60.0 | `quay.io/biocontainers/bioconductor-limma:3.66.0--r45h01b2380_0` | Law 2014, PMID 24485249 | 5,022 | 2,919 |

## enrichment  (4)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `clusterprofiler` | 4.12.0 | `quay.io/biocontainers/bioconductor-clusterprofiler:4.18.4--r45hdfd78af_0` | Wu 2021, PMID 34557778 | 9,455 | 8,823 |
| `enrichr` | 1.1.3 | `quay.io/biocontainers/gseapy:1.1.3--py311h5e00ca1_1` | Kuleshov 2016, PMID 27141961 | 8,495 | 6,133 |
| `gseapy` | 1.1.3 | `quay.io/biocontainers/gseapy:1.1.3--py311h5e00ca1_1` | Fang 2023, PMID 36426870 | 786 | 678 |
| `topgo` | 2.56.0 | `quay.io/biocontainers/bioconductor-topgo:2.62.0--r45hdfd78af_0` | Alexa & Rahnenfuhrer 2010, https://bioconductor.org/packages/topGO/ | n/a | n/a |

## epigenomics  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bismark` | 0.24.2 | `quay.io/biocontainers/bismark:0.24.2--hdfd78af_0` | Krueger & Andrews 2011, PMID 21493656 | 4,233 | 2,442 |
| `deeptools` | 3.5.5 | `quay.io/biocontainers/deeptools:3.5.5--pyhdfd78af_0` | Ramirez et al. 2016, PMID 27079975 | 6,683 | 5,101 |
| `homer` | 4.11.1 | `quay.io/biocontainers/homer:5.1--pl5321hc52dbad_1` | Heinz et al. 2010, PMID 20513432 | 11,236 | 6,361 |
| `macs3` | 3.0.1 | `quay.io/biocontainers/macs3:3.0.1--py312he57d009_3` | Zhang et al. 2008, PMID 18798982 | 15,276 | 8,484 |
| `methylkit` | 1.28.0 | `quay.io/biocontainers/bioconductor-methylkit:1.36.0--r45ha27e39d_0` | Akalin et al. 2012, PMID 23034086 | 1,664 | 1,012 |
| `methylpy` | 1.4.7 | `quay.io/biocontainers/methylpy:1.4.7--py39h0ae133c_0` | Schultz 2015, PMID 26030523 | 554 | 224 |
| `picard` | 3.2.0 | `quay.io/biocontainers/picard:3.2.0--hdfd78af_0` | Broad Institute, https://broadinstitute.github.io/picard/ | n/a | n/a |
| `tobias` | 0.16.1 | `quay.io/biocontainers/tobias:0.16.1--py312h1f1cfbb_1` | Bentsen et al. 2020, PMID 32848148 | 569 | 520 |

## func_annot  (5)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `antismash` | 7.1.0 | `antismash/standalone:7.1.0` | Blin 2023, PMID 37140036 | 1,591 | 1,399 |
| `dbcan` | 4.1.4 | `quay.io/biocontainers/dbcan:4.1.4--pyhdfd78af_0` | Zhang 2018, PMID 29771380 | 1,662 | 1,342 |
| `eggnog_mapper` | 2.1.12 | `quay.io/biocontainers/eggnog-mapper:2.1.12--pyhdfd78af_0` | Cantalapiedra 2021, PMID 34597405 | 3,330 | 2,904 |
| `gtdbtk` | 2.4.0 | `quay.io/biocontainers/gtdbtk:2.4.0--pyhdfd78af_1` | Chaumeil 2022, PMID 36218463 | 1,455 | 1,201 |
| `interproscan` | 5.67-99.0 | `quay.io/biocontainers/interproscan:5.59_91.0--hec16e2b_1` | Blum 2021, PMID 33156333 | 1,736 | 1,643 |

## metagenomics  (9)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bracken` | 2.9 | `quay.io/biocontainers/bracken:2.9--py39h9e0f934_1` | Lu et al. 2017, PMID 28655956 | n/a | n/a |
| `humann3` | 3.9 | `quay.io/biocontainers/humann:3.9--py312hdfd78af_0` | Beghini et al. 2021, PMID 33944776 | 1,715 | 1,553 |
| `kneaddata` | 0.12.0 | `quay.io/biocontainers/kneaddata:0.12.0--pyhdfd78af_0` | McIver et al. 2018, PMID 31616210 | n/a | n/a |
| `kraken2` | 2.1.3 | `quay.io/biocontainers/kraken2:2.1.3--pl5321hdcf5f25_0` | Wood et al. 2019, PMID 31779668 | 4,969 | 4,333 |
| `krona` | 2.8.1 | `staphb/krona:2.8.1` | Ondov 2011, PMID 21961884 | 1,382 | 763 |
| `lefse` | 1.1.2 | `quay.io/biocontainers/lefse:1.1.2--pyhdfd78af_0` | Segata et al. 2011, PMID 21702898 | 11,286 | 7,340 |
| `maxbin2` | 2.2.7 | `quay.io/biocontainers/maxbin2:2.2.7--h503566f_8` | Wu 2016, PMID 26515820 | 2,059 | 1,583 |
| `metabat2` | 2.17 | `quay.io/biocontainers/metabat2:2.17--h6f16272_1` | Kang 2019, PMID 31388474 | 2,893 | 2,505 |
| `metaphlan4` | 4.1.0 | `quay.io/biocontainers/metaphlan:4.1.0--pyhca03a8a_0` | Blanco-Miguez et al. 2023, PMID 36823356 | 1,019 | 840 |

## proteomics  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `comet` | 2024.02.0 | `quay.io/biocontainers/comet-ms:2026011--h9ee0642_0` | Eng 2013, PMID 23148064 | 1,275 | 734 |
| `fragpipe` ⚠️ deprecated | 22.0 | `fcyu/fragpipe:22.0` | Yu et al. 2020, PMID 33338430 | n/a | n/a |
| `maxquant` ⚠️ deprecated | 2.4.14.0 | `quay.io/biocontainers/maxquant:2.4.14.0--hdfd78af_0` | Cox & Mann 2008, PMID 19029910 | 12,649 | 5,648 |
| `msconvert` | 3.0.24238 | `chambm/pwiz-skyline-i-agree-to-the-vendor-licenses:latest` | Chambers et al. 2012, PMID 23051804 | 3,182 | 2,060 |
| `msfragger` ⚠️ deprecated | 4.1 | `fcyu/msfragger:4.1` | Kong et al. 2017, PMID 28394336 | 1,964 | 1,617 |
| `openms` | 3.2.0 | `quay.io/biocontainers/openms:3.2.0--haddbca4_5` | Rost 2016, PMID 27575624 | 501 | 317 |
| `percolator` | 3.06.1 | `quay.io/biocontainers/percolator:3.7.1--h3b5f4bd_2` | Kall et al. 2007, PMID 17952086 | 1,951 | 924 |
| `xtandem` | 15.12.15.2 | `quay.io/biocontainers/xtandem:15.12.15.2--h4464bbb_11` | Craig & Beavis 2004, PMID 14976030 | 1,931 | 322 |

## qc  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `cutadapt` | 4.9 | `quay.io/biocontainers/cutadapt:4.9--py311haab0aaa_3` | Martin 2011, doi:10.14806/ej.17.1.200 | n/a | n/a |
| `fastp` | 1.3.6 | `quay.io/biocontainers/fastp:1.3.6--h43da1c4_0` | Chen 2018, PMID 30423086 | 19,916 | 17,361 |
| `fastqc` | 0.12.1 | `quay.io/biocontainers/fastqc:0.12.1--hdfd78af_0` | Andrews S, 2010 (Babraham Bioinformatics) | n/a | n/a |
| `filtlong` | 0.2.1 | `quay.io/biocontainers/filtlong:0.2.1--hdcf5f25_4` | Wick 2021 (github.com/rrwick/Filtlong) | n/a | n/a |
| `multiqc` | 1.25.1 | `quay.io/biocontainers/multiqc:1.25.1--pyhdfd78af_0` | Ewels 2016, PMID 27312411 | 7,946 | 6,478 |
| `nanoplot` | 1.43.0 | `quay.io/biocontainers/nanoplot:1.43.0--pyhdfd78af_0` | De Coster 2023, PMID 37171891 | 575 | 456 |
| `seqkit` | 2.8.2 | `quay.io/biocontainers/seqkit:2.8.2--h9ee0642_0` | Shen 2016, PMID 27706213 | 2,560 | 2,194 |
| `trimgalore` | 0.6.10 | `quay.io/biocontainers/trim-galore:0.6.10--hdfd78af_0` | Krueger 2015, https://github.com/FelixKrueger/TrimGalore | n/a | n/a |

## repeat  (3)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `earlgrey` | 4.5.0 | `quay.io/biocontainers/earlgrey:4.5.0--h4ac6f70_2` | Baril 2024, PMID 38577785 | 169 | 128 |
| `repeatmasker` | 4.1.7 | `dfam/tetools:1.89` | Smit 2015 (repeatmasker.org) | n/a | n/a |
| `repeatmodeler` | 2.0.5 | `dfam/tetools:1.89` | Flynn 2020, PMID 32300014 | 3,090 | 2,788 |

## rnaseq_align  (7)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `hisat2` | 2.2.1 | `quay.io/biocontainers/hisat2:2.2.1--h87f3376_4` | Kim 2019, PMID 31375807 | 10,968 | 9,680 |
| `kallisto` | 0.51.1 | `quay.io/biocontainers/kallisto:0.51.1--h2b92561_2` | Bray 2016, PMID 27043002 | 7,856 | 5,298 |
| `rsem` | 1.3.3 | `quay.io/biocontainers/rsem:1.3.3--pl5321h077b44d_12` | Li & Dewey 2011, PMID 21816040 | 16,258 | 9,456 |
| `salmon` | 2.3.1 | `quay.io/biocontainers/salmon:2.3.1--hfa8f182_0` | Patro 2017, PMID 28263959 | 9,687 | 7,499 |
| `star` | 2.7.11b | `quay.io/biocontainers/star:2.7.11b--h43eeafb_0` | Dobin 2013, PMID 23104886 | 41,990 | 29,078 |
| `stringtie` | 2.2.3 | `quay.io/biocontainers/stringtie:2.2.3--h29c0135_1` | Pertea 2015, PMID 25690850 | 10,134 | 7,701 |
| `subread` | 2.0.6 | `quay.io/biocontainers/subread:2.0.6--he4a0461_2` | Liao 2014, PMID 24227677 | 21,327 | 15,592 |

## single_cell  (8)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bustools` | 0.43.2 | `quay.io/biocontainers/bustools:0.43.2--he1fd2f9_2` | Melsted 2019, PMID 31073610 | 122 | 108 |
| `cellranger` | 7.2.0 | `litd/docker-cellranger:v7.2.0` | Zheng et al. 2017, PMID 28091601 | 5,666 | 4,102 |
| `harmony` | 1.2.1 | `quay.io/biocontainers/harmonypy:0.0.10--pyhdfd78af_0` | Korsunsky 2019, PMID 31740819 | 7,697 | 6,723 |
| `monocle3` | 1.3.7 | `quay.io/biocontainers/r-monocle3:1.4.26--r44h9948957_0` | Cao et al. 2019, PMID 30787392 | 426 | 371 |
| `scanpy` | 1.10.1 | `quay.io/biocontainers/scanpy:1.7.2--pyhdfd78af_0` | Wolf et al. 2018, PMID 29409532 | 6,692 | 5,617 |
| `scrublet` | 0.2.3 | `quay.io/biocontainers/scrublet:0.2.3--pyh5e36f6f_1` | Wolock 2019, PMID 30954476 | 2,184 | 1,854 |
| `seurat` | 5.0.1 | `satijalab/seurat:5.0.0` | Hao et al. 2024, PMID 37231261 | 3,602 | 2,821 |
| `starsolo` | 2.7.11b | `quay.io/biocontainers/star:2.7.11b--h43eeafb_0` | Dobin et al. 2013, PMID 23104886 | 41,990 | 29,078 |

## struct_annot  (5)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `augustus` | 3.5.0 | `quay.io/biocontainers/augustus:3.5.0--pl5321h9716f88_9` | Stanke 2008, PMID 18218656 | 1,990 | 1,263 |
| `bakta` | 1.9.4 | `quay.io/biocontainers/bakta:1.9.4--pyhdfd78af_0` | Schwengers 2021, PMID 34739369 | 919 | 792 |
| `braker3` | 3.0.8 | `teambraker/braker3:v3.0.8` | Gabriel 2024, PMID 38866550 | 487 | 370 |
| `liftoff` | 1.6.3 | `quay.io/biocontainers/liftoff:1.6.3--pyhdfd78af_0` | Shumate & Salzberg 2021, PMID 33320174 | 733 | 669 |
| `prokka` | 1.14.6 | `staphb/prokka:1.14.6` | Seemann 2014, PMID 24642063 | 14,442 | 9,722 |

## variant_calling  (4)

| Tool | Version | Image | Citation | Total cites | Cites 2021–2025 |
|---|---|---|---|--:|--:|
| `bcftools` | 1.21 | `quay.io/biocontainers/bcftools:1.21--h8b25389_0` | Danecek 2021, PMID 33590861 | 11,759 | 10,492 |
| `freebayes` | 1.3.7 | `quay.io/biocontainers/freebayes:1.3.7--h6a68c12_2` | Garrison & Marth 2012, arXiv:1207.3907 | n/a | n/a |
| `gatk4` | 4.6.1.0 | `quay.io/biocontainers/gatk4:4.6.1.0--py310hdfd78af_0` | McKenna 2010, PMID 20644199 | 16,785 | 7,994 |
| `snpeff` | 5.2 | `quay.io/biocontainers/snpeff:5.2--hdfd78af_1` | Cingolani 2012, PMID 22728672 | 9,399 | 5,402 |

