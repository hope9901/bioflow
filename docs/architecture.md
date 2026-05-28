# Architecture

```
┌─────────────────────────────────────────────────────────┐
│  CLI  recipe / recommend / custom / run / db / setup / llm │
└──────────────────────┬──────────────────────────────────┘
                       │
       ┌───────────────▼──────────────────────┐
       │   Python SDK + Orchestrator          │
       │  @stage · @pipeline · cache · retry  │
       │  Hardware filter · Report builder    │
       └──────┬──────────────────┬────────────┘
              │                  │
   ┌──────────▼──────┐  ┌────────▼────────────────┐
   │  Tool Registry  │  │  Docker Engine          │
   │ 110 YAML tools  │  │  Sibling-container ptn  │
   │  in 16 categories│  │  Live log streaming    │
   └─────────────────┘  └─────────────────────────┘
```

`bioflow` is never a daemon.  Every command spins up briefly, does its
work, and exits.

## Key components

| Layer | Responsibility |
|---|---|
| **CLI** (`bioflow/cli.py`) | Tier-B entry point — recipe / recommend / custom / run / db / llm |
| **SDK** (`bioflow/sdk.py`) | `@stage` / `@pipeline` decorators, caching, retry, parallel fan-out |
| **Registry** (`registry/tools/*.yaml`) | 110 tool definitions; single source of truth for images + hardware specs |
| **Hardware filter** (`bioflow/core/compatibility.py`) | classifies tools `installable` / `runnable_slow` / `incompatible` |
| **Runner** (`bioflow/core/runner.py`) | sibling-container execution via the host Docker socket |
| **Recipes** (`bioflow/recipes/`) | 19 curated, registered pipelines |
| **Update system** (`update/`) | freshness check, release-watch, benchmark, approve |

## Two execution surfaces

- **Recipes** — Python `@stage`/`@pipeline` chains, full control flow,
  parallelism, retry.  `bioflow recipe run <name>`.
- **Presets** — declarative YAML chains of registry tool IDs, scored
  against the host by the hardware filter.  `bioflow recommend --preset <id>`.

Presets that have a recipe equivalent link to it via a `recipe:` field.

## Container strategy

- **Core image**: `python:3.12-slim` + Docker client + bioflow (~1 GB).
- **Tool images**: BioContainers / community images, pulled on first use.
- **Sibling-container pattern**: the core mounts the host Docker socket
  and launches tool containers as siblings — **not** Docker-in-Docker.
- **Shared volumes**: `/workspace` (I/O) and `/refs` (reference DBs)
  mounted into every container; data flows file-based between stages.

For the full rationale (and what's intentionally out of scope) see the
[design notes](DESIGN.md).
