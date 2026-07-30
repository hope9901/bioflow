# End-to-end test coverage & external data

bioflow ships **three tiers** of automated recipe testing:

* a **smoke matrix** ([`tests/integration/test_recipe_smoke_matrix.py`](https://github.com/hope9901/bioflow/blob/main/tests/integration/test_recipe_smoke_matrix.py))
  that runs a recipe's *first* stage against its real container — currently
  five recipes (`prokaryote_assembly`, `rnaseq_deg`, `amr_vf_catalogue`,
  `chip_seq`, `germline_variants`), not all of them,
* a **full end-to-end** suite
  ([`tests/integration/test_full_pipeline_e2e.py`](https://github.com/hope9901/bioflow/blob/main/tests/integration/test_full_pipeline_e2e.py))
  that runs a recipe's **entire chain** on a committed fixture and asserts
  real outputs flow between stages, and
* **stage-level guards**
  ([`tests/integration/test_fixture_backed_swaps.py`](https://github.com/hope9901/bioflow/blob/main/tests/integration/test_fixture_backed_swaps.py))
  for recipes whose *tail* needs more data than a committed fixture can give —
  they assert each stage hands the next one the artifact it expects.

All three run in the nightly Docker job.

A recipe gets a committed full-e2e fixture only when its inputs are small
enough to live in git (a few-kb genome, synthetic reads).  Recipes that
need a **multi-GB reference index or an external database** can't — the
fixture would dwarf the repo and the download would make CI flaky.  Their
external assets are catalogued for `bioflow db fetch`.

!!! warning "One recipe has no automated coverage"
    `download_taxon` appears in none of the three tiers — it is exercised by
    hand, not by CI.  A change to it is not caught by any test, so treat it as
    unverified until a smoke case or fixture exists.

## Validated end to end (10)

Each runs its full chain in CI (the nightly job) on a fixture under
[`data/test/`](https://github.com/hope9901/bioflow/tree/main/data/test).

| Recipe | Chain | Fixture |
|---|---|---|
| `prokaryote_assembly` | fastp → SPAdes → QUAST → Prokka | `phix_small/` |
| `amr_vf_catalogue` | ABRicate × N (bundled DBs) | `genomes_small/` |
| `ani_matrix` | all-vs-all FastANI | `genomes_small/` |
| `pangenome` | Prokka × N → Roary | `genomes_small/` |
| `gwas` | Scoary on a Roary GPA + phenotype | `gwas_small/` |
| `cafe_evolution` | CAFE5 gene-family dynamics | `cafe_small/` |
| `phylogeny` | single-copy core → MAFFT × N → IQ-TREE | `phylo_small/` |
| `rnaseq_deg` | fastp → Salmon → DESeq2 → enrichment + MultiQC | `rnaseq_small/` |
| `methylation_wgbs` | TrimGalore → Bismark (prep + align) → methylKit | `methyl_small/` |
| `cog_enrichment` | DIAMOND makedb → blastp → per-bucket COG-category aggregation | `cog_small/` + `gwas_small/` |

## Guarded at the stage level on a tiny fixture (3)

A full chain isn't meaningful for these — Scanpy's PCA/clustering needs far
more than a 3-gene toy, and Percolator's semi-supervised FDR far more than 3
PSMs — so the guard stops where the fixture stops being honest and asserts the
hand-off instead.

| Recipe | Guarded | Fixture |
|---|---|---|
| `scrna_seq` | `--set counter=kb`: `kb ref` → `kb count` emits the 6-cell × 3-gene matrix (+ barcode/gene sidecars) Scanpy's reader consumes | `scrna_small/` |
| `proteomics_dda` | Comet emits a **tab-delimited `.pin`** — Percolator rejects `.pep.xml`, so this is the regression guard for that fix | `proteomics_small/` |
| `metagenome_assembly` | fastp → MEGAHIT assembles 2 contigs; MetaBAT2 computes depth + writes the `bins/` layout CheckM2 consumes (real bins need marker genes a tiny fixture lacks) | `metagenome_small/` |
| `joint_genotyping` | 2 samples → HaplotypeCaller gVCF → CombineGVCFs → GenotypeGVCFs yields a 2-sample `cohort.vcf.gz` with 5 planted SNPs (SnpEff excluded — it downloads its DB at run time) | `cohort_small/` + `phix_small/` |
| `atac_seq` | trim → Bowtie2 align → Picard dedup → MACS3 peaks (index built in-test; TOBIAS footprinting needs a real motif/genome) | `phix_small/` |
| `eukaryote_assembly` | NanoPlot → hifiasm → assembly.fasta (`--set assembler=hifiasm`; Flye SIGFPEs on a tiny genome, Medaka/compleasm need model/DB) | `hifi_small/` |
| `metagenomics_profile` | fastp → Kraken2 classifies 600 read-pairs against a hand-built 2-taxon DB (Bracken excluded — it crashes walking a DB this small; real runs use the 8 GB standard DB) | `kraken_small/` |

## Requires external reference data (10)

A full e2e for these is gated on a reference the user supplies.  Only
`chip_seq` and `germline_variants` are in the smoke matrix; the rest carry no
automated check at all (see the warning above).  The **`bioflow db`** column gives the
catalog key for `bioflow db fetch <key> --dest /refs` where one exists
(see `bioflow db --help`); otherwise it points at the upstream source.

| Recipe | Needs | `bioflow db fetch` |
|---|---|---|
| `metagenomics_profile` | Kraken2 database (fastp → classify is stage-guarded above) | `kraken2_standard_8gb` |
| `metagenome_assembly` | CheckM2 diamond DB (assemble → binning is stage-guarded above) | upstream: `checkm2 database --download` |
| `scrna_seq` | STAR genome index + 10x barcode whitelist (the `kb` swap is stage-guarded above) | `10x_whitelist_v3` (+ build STAR index from `gencode_grch38` + genome FASTA) |
| `chip_seq` | Bowtie2 index + reference FASTA + GTF | `bowtie2_grch38_noalt`, `gencode_grch38` |
| `germline_variants` | reference FASTA + SnpEff DB (± GATK known-sites) | SnpEff DB auto-downloads by name; `dbsnp_grch38`, `mills_indels_grch38` for BQSR |
| `joint_genotyping` | as `germline_variants` + a cohort sample sheet (the gVCF → cohort path is stage-guarded above) | as above |
| `proteomics_dda` | protein FASTA DB + Comet params + raw spectra (search → `.pin` is stage-guarded above) | `uniprot_sprot` (spectra are vendor files) |

!!! note "BWA / SnpEff indexes are built for you"
    `germline_variants` and `joint_genotyping` build the BWA index and the
    GATK `.dict` / `.fai` in place if absent, and SnpEff downloads its
    organism database by name — so for a bacterium you really only supply
    a reference FASTA.  They're listed here because the SnpEff download
    and a realistic reference make a committed, deterministic fixture
    impractical, not because setup is heavy.

## Utility (1)

| Recipe | Note |
|---|---|
| `download_taxon` | Pure NCBI Datasets fetch (no Docker); network-dependent, so it has no committed fixture. |
