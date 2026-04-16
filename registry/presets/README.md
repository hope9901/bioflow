# Presets (recommended pipelines)

This folder is intentionally empty in the skeleton.

Presets are **the user-specified recommended tool combinations**. Each preset is
a YAML that pins one tool per pipeline stage. The planner resolves it against
the live registry at run time so that if a pinned tool is missing/incompatible
on the host, a substitute from the same stage group can be proposed.

Planned presets (names will map to files in this folder):

- `eukaryote_denovo_hifi.yaml`
- `eukaryote_denovo_hybrid.yaml`
- `eukaryote_resequencing.yaml`
- `prokaryote_denovo_short.yaml`
- `prokaryote_denovo_hybrid.yaml`
- `rnaseq_deseq2_standard.yaml`

Preset YAML shape (to be finalized in step 8):

```yaml
id: prokaryote_denovo_short
pipeline: genome_assembly
applies_to:
  species: prokaryote
  read_type: short
  mode: de_novo
stages:
  - stage: genome_assembly.step1
    tool: fastp
  - stage: genome_assembly.step2
    tool: spades
  - stage: genome_assembly.step3
    tool: quast
  - stage: genome_assembly.step4
    skip: true           # prokaryote: skip repeat masking
  - stage: genome_assembly.step5
    tool: prokka
  - stage: genome_assembly.step6
    tool: eggnog_mapper
```
