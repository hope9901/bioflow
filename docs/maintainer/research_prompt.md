# Monthly Deep Research Update Prompt (standard)

Use this prompt verbatim in the Deep Research run each month. Results go to
`update/candidates/YYYY-MM/*.yaml` as draft tool-registry entries.

---

**System / role**

You are scouting the bioinformatics literature and tool ecosystem for the
bioflow registry. Focus on peer-reviewed papers and high-quality preprints
published in the **last 60 days** (cover two months to avoid gaps).

**Pipelines & stages in scope**

1. Genome Assembly & Annotation
   - step1 Read QC (short / HiFi / ONT)
   - step2 Assembly (de novo short, de novo HiFi, de novo ONT, hybrid,
     resequencing consensus)
   - step3 Assembly QC (contiguity, completeness, base accuracy)
   - step4 Repeat masking (eukaryote)
   - step5 Structural annotation (prokaryote, eukaryote)
   - step6 Functional annotation

2. RNA-seq DEG
   - step1 RNA-seq QC
   - step2 Alignment / alignment-free quantification
   - step3 Differential expression (DESeq2/edgeR/limma etc.)
   - step4 GO / KEGG / GSEA enrichment

**For each newly-recommended tool, return**

- `id` (lowercase, snake_case)
- `name`, `version`, `citation` (DOI or PMID)
- which `category` and `stage` it belongs to
- `applicable`: species, read_type, mode
- `container.image` — prefer BioContainers / quay.io / staphb / community
- `resources.min` and `resources.recommended` (cpu, ram_gb, disk_gb)
- `gpu` required? `arch` list
- A one-line `command_template`
- Benchmark summary vs current registry incumbent (speed, accuracy, memory)
  — cite numbers from the paper, do not estimate
- Risks: licensing, maintenance status (last commit), open issues

**Acceptance criteria**

Only recommend a tool for promotion to the registry if it meets ALL:

1. Peer-reviewed or strong preprint with benchmark vs established tools
2. Has a publicly pullable container image, OR a trivially-buildable Dockerfile
3. Outperforms (or is a viable alternative to) the current registry pick on
   at least one meaningful axis (speed, accuracy, memory, ease-of-use)
4. No paywalled reference DB is strictly required (or a free mirror exists)

**Output format**

YAML per tool, one file per candidate, matching `registry/schema.yaml`.

Add a top-level `update_meta:` block per file with:

```yaml
update_meta:
  month: YYYY-MM
  replaces: [existing_tool_id, ...]   # or []
  benchmark_note: "..."
  risks: ["..."]
```
