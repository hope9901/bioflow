# Operational notes

> **Audience**: whoever maintains the registry and CI next.
> `CHANGELOG.md` records *what changed*. This page records the things a
> changelog entry can't carry: what state the guards are in, which upgrades are
> deliberately **held**, and the traps that cost a debugging session to find.

Last reviewed: **2026-08-03**.

---

## Where things stand

| | Count | Guard |
|---|---|---|
| Recipes registered | 20 | `tests/unit/test_recipe_coverage_inventory.py` |
| — with automated coverage | **20 (all)** | UNCOVERED is empty and must stay empty |
| Active tools, digest-pinned | 134 / 134 | `scripts/pin_digests.py --audit` (CI, blocking) |
| Unit tests | 805 | CI on Python 3.9 / 3.11 / 3.12 |

Coverage tiers (see [E2E coverage](../reference/e2e-coverage.md) for the detail):
**5** smoke · **10** full end-to-end · **7** stage-guarded · **1** wiring-only.

Linters are pinned on purpose — `ruff==0.16.0`, `mypy==1.19.1` — because the dev
extras only set lower bounds, so an unpinned install tracks whatever released
last and can fail an unrelated PR. Bump deliberately, fixing the new findings in
the same PR.

---

## The one manual control

Everything else in this list is enforced by a test. This one isn't, by choice:

> **Before bumping a tool, run the new image and confirm the binary works.**

A digest-pinned image with a matching version label can still ship a **broken
binary**, and no guard catches that for the 78 tools no recipe hard-codes
(they're reachable only through `bioflow custom`). Automating it would need a
per-tool `smoke:` command in the registry, since the tool id rarely matches the
executable (`trnascan_se` → `tRNAscan-SE`, `spades` → `spades.py`, `kb_python` →
`kb`). That was considered and deliberately not built — the manual check has
caught every instance so far.

When a recipe *does* exercise the tool, run that instead: it's strictly better
evidence. SPAdes was verified by the `prokaryote_assembly` full chain, Kraken2 by
the `metagenomics_profile` guard, Salmon by `rnaseq_deg`.

---

## Held back on purpose — do not "update" these

| Tool | Pinned at | Why the newer version is rejected |
|---|---|---|
| `kb_python` | 0.28.2 (`--pyhdfd78af_2`) | 0.30.2's `--pyh106432d_0` build ships **no working kallisto** — `kb ref` dies with `UnsupportedOSError: Failed to find compatible kallisto binary`. Re-bump only after confirming the kallisto binary loads. |
| `bowtie2` | 2.5.1 | 2.5.4 and 2.5.5 bundle a samtools that can't load `libdeflate.so.0`, so `bowtie2 \| samtools sort` exits 127. The whole point of the StaPH-B image is a working samtools; those builds don't have one. |

Both were found by running the container, not by reading a tag.

---

## Open candidates

| Candidate | State |
|---|---|
| `gecco` 0.11.0 (`2026-08/`) | **Ready to apply.** `gecco:0.11.0--pyhdfd78af_0` was built 2026-07-31; the candidate resolved the real tag and carries no "unverified image tag" risk. Needs the run-the-container check, then registry + digest. |
| `comet` 2026.02.1 (`2026-08/`) | Parked — no BioContainer (quay's newest is 2026.01.1). |
| `scanpy` 1.12.3 (`2026-07/`) | Parked — the self-built image isn't pushed to GHCR. |

A parked candidate is filed but **cannot** be applied: there is no image to pin,
so there is nothing to verify. Re-check occasionally; nothing else blocks them.

`update/candidates/2026-06/comet.yaml` (2026.02.0) is superseded by the 2026-08
candidate but survives pruning, because `--prune` compares each candidate against
the *registry*, not against other candidates. Harmless; delete it by hand
whenever the comet bump lands.

---

## Traps that cost a session to find

**Applying a version bump touches two places.** The registry YAML
(`registry/tools/<id>.yaml` — `version` and `image`, then
`scripts/pin_digests.py --force <id>` for the digest) **and** every hard-coded
`@stage(image=...)` in the recipes. They must agree or
`test_recipe_registry_alignment.py` fails. release_watch candidates deliberately
carry **no** digest — `pin_digests.py` is the single digest authority, and a
candidate that inherited the old digest would pin the *old* image under a *new*
version number.

**Python 3.9 is the floor, and it bites at import time.** Keep
`typing.Optional` / `Union`; PEP 604 (`X | None`) is 3.10+ *at runtime*, and
`from __future__ import annotations` does not save you, because Pydantic models
and Typer commands resolve annotations through `get_type_hints()`. `ruff`'s
`UP007` / `UP045` are disabled for exactly this reason. PEP 585 builtins
(`list[x]`, `dict[x]`) *are* 3.9-safe and already adopted.

**Local green ≠ CI green, twice over.**
- *Platform*: development happens on Windows, CI runs Linux. POSIX-only ruff
  rules are silently skipped locally — `EXE001` (shebang without the executable
  bit) passed on Windows and failed the Linux lint job. Verify from Windows via
  the staged git mode (`100755`).
- *Environment*: local mypy sees Python 3.9 + numpy 1.26; CI sees 3.12 + numpy
  2.x + `pynvml` installed. A config-only change went green locally and red in
  CI. Check mypy config changes in a py3.11+ venv with numpy 2.x first.

**Fixtures can pick up build artifacts.** A verification run once let
`prepare_reference` build a BWA index *inside* `data/test/cohort_small/`, and
`git add` swept the `.fai` / `.dict` / `.bwt` files in. The fixture now carries a
`.gitignore`; check `git status` on the fixture directory after any run that
writes into it.

**Docker images accumulate fast.** A full verification pass left 48 images /
61 GB. `docker image prune -a` reclaims it, but on Windows the WSL2 disk
(`%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx`) does **not** shrink on its
own — the space is freed inside the VHDX, not returned to the drive. Compact it
from an elevated PowerShell:

```powershell
wsl --shutdown
$s = "$env:TEMP\compact.txt"
@"
select vdisk file="$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
"@ | Set-Content -Encoding ASCII $s
diskpart /s $s
```

`bioflow cache size` / `bioflow db size` cover the workspace side of the same
problem.

---

## Known gaps

- **release_watch only watches GitHub releases.** Seven tools report
  `no_releases` (skani, kofamscan, metabat2, htseq, …) — they publish no GitHub
  release, so upstream drift for them is invisible. Their BioContainers *are*
  rebuilt. Extending the watcher to check quay.io tags directly (reusing
  `resolve_biocontainer_image`) would close this, and would also catch the cases
  where bioconda is ahead of GitHub.
- **No automated smoke test for registry-only tools** — see
  [The one manual control](#the-one-manual-control) above.
