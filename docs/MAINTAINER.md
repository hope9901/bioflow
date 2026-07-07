# Maintainer guide

> **Audience**: the single person who owns the GitHub repo and pushes
> registry updates.  Researchers using bioflow as a tool don't need
> anything in this file — they just `git pull`.

The registry of tool YAMLs evolves over time as new bioinformatics
software ships.  bioflow runs **5 update cadences** to keep it fresh —
this file documents the monthly Cowork ↔ local-cron pipeline.  For the
full multi-cadence model (daily freshness check, weekly release watch,
quarterly deep audit, event-driven PR smoke test) see
[`UPDATE_CADENCES.md`](maintainer/UPDATE_CADENCES.md).

bioflow's design intentionally splits the update work
into **two roles**:

| Role | Who | Does |
|---|---|---|
| **A · maintainer**  | you (one person) | Deep Research → benchmark → `git push` |
| **B · researchers** | everyone else    | `git pull` |

This file documents Role A.  None of it should be installed on a
researcher's machine.

---

## The pipeline at a glance

```
┌── Cowork scheduled task (off your machine) ──────┐
│  monthly Deep Research → YAML drafts → PR        │
│  to update/candidates/<YYYY-MM>/ on GitHub       │
└──────────────────────────┬───────────────────────┘
                           │  merge the PR
                           ▼
┌── Your machine's cron / Task Scheduler ──────────┐
│  bioflow update auto --auto-approve --git-push   │
│   1. walk update/candidates/                     │
│   2. smoke-test each YAML                        │
│   3. promote passes → registry/                  │
│   4. git commit + git push to origin             │
└──────────────────────────┬───────────────────────┘
                           │  GitHub repo updated
                           ▼
                  researchers run `git pull`
```

Two separate schedulers because the work splits cleanly:

- **Deep Research** needs an LLM + the open internet — runs on Cowork's
  servers even when your laptop is asleep.
- **Benchmarking** needs Docker + your git credentials — only your
  machine has those, so the local cron runs there.

The point where they meet is files under
`update/candidates/<YYYY-MM>/*.yaml`.

---

## Part 1 · Local scheduled task (`bioflow update auto`)

### One-time install

**Windows** (elevated PowerShell):

```powershell
cd C:\path\to\bioflow
.\scripts\install-schedule-windows.ps1 -AutoApprove -GitPush
```

Flags:

| Flag | Effect |
|---|---|
| `-AutoApprove` | Promote any candidate whose smoke test passes |
| `-Real`        | Use the real DockerBackend (slow — pulls every image) |
| `-GitPush`     | After approval, `git add` / `git commit` / `git push` |
| `-GitRemote`   | Default `origin` |
| `-GitBranch`   | Default current HEAD |
| `-RunTime`     | Default `02:30` |
| `-Uninstall`   | Remove the task |

**Linux / macOS** (no `sudo` needed for user-scope cron):

```bash
cd /path/to/bioflow
./scripts/install-schedule-cron.sh --auto-approve --git-push
```

Both helpers register the job at **02:30 on the 1st of every month**.
A JSON report lands at `update/last_run.json` after each run.

### What the task does, step by step

1. Walk `update/candidates/**/*.yaml`.
2. For each, run `update.benchmark.smoke_test()` — validates against
   `registry/schema.yaml`, resolves a test dataset, optionally pulls
   the image and runs it.
3. Write `update/last_run.json` with per-candidate pass/fail.
4. With `--auto-approve`: call `bioflow.core.approve.approve_candidate()`
   for each passing YAML → file lands under `registry/tools/<cat>/`.
5. If any candidate was approved, **regenerate the registry-derived
   artifacts** so the freshness CI gates stay green on the push:
   `scripts/io_contracts.py update` (re-blesses the I/O contract snapshot —
   a bump that changes a tool's input/output formats is the drift the
   `io-contracts` gate flags) and `scripts/gen_docs.py` (the README + docs
   tables).  Skipped when running against a non-default `--registry` (so tests
   never touch the real snapshot).
6. With `--git-push`:
   - `git add registry/ update/CHANGELOG.md README.md docs/reference update/last_run.json`
     (`registry/` already carries the refreshed `io_contracts.json`)
   - skip the commit cleanly if nothing was staged
   - `git commit -m "chore(registry): monthly auto-update YYYY-MM-DD — N new tool(s)"`
   - `git push origin <branch>`

### Manual one-shot

The scheduled task is just a wrapper around this command:

```bash
bioflow update auto                              # safe default — benchmark + report, no changes
bioflow update auto --auto-approve               # also promote passes
bioflow update auto --auto-approve --git-push    # full automation
bioflow update auto --real                       # actually pull each container image
bioflow update auto --candidates-dir DIR         # override the search root
bioflow update auto --report PATH                # custom JSON report location
```

Exit codes (useful for cron failure-mail rules):

| Code | Meaning |
|---|---|
| 0 | All candidates passed (or none found) |
| 1 | At least one candidate failed OR a git operation failed |

### Credentials

`git push` uses your shell's normal git auth — Git Credential Manager
on Windows, SSH key + agent on Linux/macOS, or a PAT pre-configured in
your remote URL.  **bioflow never stores tokens.**

If your scheduled task can't push (cron has no terminal for credential
prompts), pre-stage credentials with one of:

```bash
git config --global credential.helper store        # cache to disk
gh auth setup-git                                  # GitHub CLI
ssh-add ~/.ssh/id_ed25519                          # SSH agent persistent across reboots
```

---

## Part 2 · Cowork scheduled task (Deep Research)

The off-machine half of the workflow.  Drives an LLM agent on Anthropic
Cowork to do the research and emit YAML candidates as a PR.

### Prompt

The exact prompt to register is at:

```
docs/maintainer/cowork_schedule_prompt.md
```

Copy the fenced code block from that file into Cowork's "scheduled
task" → prompt field.  Configure:

| Cowork field | Recommended value |
|---|---|
| Schedule | `0 9 1 * *` (monthly, 09:00 local) |
| Model    | `claude-3.5-sonnet` or newer |
| Tools    | WebSearch, WebFetch, plus GitHub MCP if you have one wired up |
| Workspace | a worktree of this repo (for direct file writes) — optional |

### What the Cowork agent produces

- A PR on this repo named `auto-update/<YYYY-MM>` containing new files
  under `update/candidates/<YYYY-MM>/`, OR
- (if GitHub MCP isn't available) a chat message listing the candidate
  YAMLs — you copy them into the right path manually.

The agent **never** touches `registry/` directly.  Promotion happens
only after the local scheduled task in Part 1 benchmarks them.

### Acceptance criteria the agent applies

A candidate is only added to a PR if it satisfies all four:

1. Peer-reviewed paper or strong preprint with a benchmark vs an
   established tool.
2. Publicly pullable container image (BioContainers / staphb / quay.io
   preferred).
3. Measured advantage over the current registry incumbent on at least
   one axis (speed, accuracy, memory, ease-of-use).
4. No paywalled DB is strictly required (or a free mirror exists).

The agent will commit to **0** candidates for a month if nothing
qualifies — that's the intended outcome, not a failure.

---

## Part 3 · The two schedulers don't talk

There's no IPC between Cowork and your local cron.  Their handoff is
the contents of `update/candidates/<YYYY-MM>/` after you merge the PR.

- Cowork fires on the 1st at 09:00 KST → PR open by mid-morning.
- You merge the PR sometime during the month (or never, if the
  candidates look wrong).
- Local cron fires on the 1st of the next month at 02:30 → benchmarks
  whatever ended up in `update/candidates/` and pushes.

If you want the local cron to pick up Cowork's output the same day,
move its trigger to e.g. the 15th of the month (cron: `0 2 15 * *`).

---

## Part 4 · Troubleshooting

### "git commit failed"

Most common cause: nothing was actually staged (no candidate passed,
no CHANGELOG changes).  `bioflow update auto` handles this — it
detects an empty staged set via `git diff --cached --quiet` and skips
the commit.  If you see this error, check `update/last_run.json` to
see if any candidate passed.

### "git push failed: authentication required"

Your scheduled task isn't seeing your credentials.  See "Credentials"
above; cron / Task Scheduler typically can't prompt.

### Cowork PR has weird YAMLs

The prompt's section 7 (self-check) catches the obvious mistakes but
not all of them.  Use bioflow's own validator before merging:

```bash
git checkout auto-update/<YYYY-MM>
bioflow update auto --candidates-dir update/candidates/<YYYY-MM>
cat update/last_run.json | python -m json.tool
```

Reject the PR if anything that should pass actually fails.

### Manually promote a single candidate

```bash
bioflow update approve --candidate update/candidates/2026-06/mytool.yaml
```

Bypasses both schedulers.  Useful for emergency additions.

### I/O contract drift on a version bump

Every tool declares the data formats it consumes/produces (`input_types` /
`output_types`).  A version bump that also **changes those formats** can break a
downstream recipe stage that fed on the old shape of the output.  To make that
loud, `registry/io_contracts.json` snapshots every tool's
`(version, inputs, outputs)`, and CI's `io-contracts` job fails whenever the
snapshot is stale:

```bash
python scripts/io_contracts.py check    # what CI runs; lists any drift
python scripts/io_contracts.py update   # regenerate after verifying recipes
```

When you bump a tool:

- **I/O unchanged** (most bumps) — `check` reports it as *version-only*; just
  run `update` and commit the refreshed snapshot.
- **I/O changed** — `check` prints the format diff **and the recipes that pin
  the tool**.  Re-run those recipes (or their e2e/smoke tests) to confirm the
  new output still feeds the next stage, adjust the recipe command if not, then
  run `update`.  This is the mechanism that keeps recipes and user-defined
  pipelines working across upgrades — the bump can't ship until the contract is
  re-blessed.

### Behaviour-check a bump BEFORE you push

A version bump can keep the same I/O contract yet silently break a tool — e.g.
the staphb `prokka:1.15.6` repackage ran fine but emitted **0 CDS**, so
`prokaryote_assembly` + `pangenome` only went red in the *scheduled nightly*
(an after-the-fact failure email).  The `command -v` capability guard can't
catch this — the binary exists; it just misbehaves.

So after any bump, and **before you commit/push**, run:

```bash
python scripts/verify_bump.py                 # auto-detects tools changed vs origin/main
python scripts/verify_bump.py prokka bcftools # or name them explicitly
```

It launches each bumped tool's **pinned image** and runs its real operation on
a tiny generated input (`[real]`), failing if the output is missing/empty —
exactly the prokka-0-CDS class of break.  Tools whose real op needs a large
runtime database the recipe supplies (kraken2 / snpEff / CheckM2 / …) fall back
to a `[live]` responds-probe and still need the recipe's own e2e for a full
check.  Exit non-zero ⇒ do not push.  `scripts/bump_tools.py` prints this
command in its "next" steps.

---

## Part 5 · Cutting a PyPI release

bioflow is published from `main` via a tag-driven GitHub Actions
workflow (`.github/workflows/release.yml`) that pushes to TestPyPI →
PyPI → GitHub Releases.  Authentication uses **PyPI Trusted Publishing
(OIDC)**, so no long-lived tokens live in the repo.

### One-time PyPI setup (per project, per environment)

Do this once for **TestPyPI** (https://test.pypi.org) and once for
**PyPI** (https://pypi.org).  Both sites have the same UI.

> **Distribution name note**: the PyPI namespace `bioflow` was taken
> in 2018 by an unrelated dormant project, so we publish under
> `bioflowkit`.  The Python import name (`from bioflow import …`),
> the CLI command (`bioflow`), and the GitHub repository
> (`hope9901/bioflow`) are all unchanged.

1. Log in to (Test)PyPI.
2. Account → **Publishing** → **Add a new pending publisher**.
3. Fill in:
   - **PyPI project name**: `bioflowkit`
   - **Owner**: `hope9901`
   - **Repository**: `bioflow`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi` (for prod) or `testpypi` (for test)
4. Save.

GitHub side: **Settings → Environments → New environment**.  Create
one named `testpypi` and one named `pypi`.  No secrets needed — the
OIDC token is minted at runtime.  Optionally add **Required reviewers**
to the `pypi` environment so a release can't promote without your
click.

### Release procedure

```bash
# 1. Make sure main is green
git fetch origin && git status
python -m pytest tests/unit -q              # must be all-green
python -m ruff check .

# 2. Bump version in two places (kept in sync; CI guards against drift)
#    - pyproject.toml::project.version
#    - bioflow/__init__.py::__version__
$EDITOR pyproject.toml bioflow/__init__.py

# 3. Move the CHANGELOG's [Unreleased] section to [X.Y.Z] — YYYY-MM-DD
$EDITOR CHANGELOG.md

# 4. Commit + tag
git add pyproject.toml bioflow/__init__.py CHANGELOG.md
git commit -m "chore: release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags

# 5. Watch the workflow at
#    https://github.com/hope9901/bioflow/actions/workflows/release.yml
#    Order: build → testpypi → pypi → github
#    Each environment may prompt for approval if you set required reviewers.

# 6. Verify the published artifact
pip install --upgrade bioflowkit==X.Y.Z    # PyPI distribution name
bioflow doctor                              # CLI command stays `bioflow`
```

### Hotfix release (0.Y.Z → 0.Y.(Z+1))

Patch releases are for bug fixes only.  Same procedure, but branch off
`main` and *only* include the fix + a CHANGELOG entry — no
behavioural changes.

### If something goes wrong mid-pipeline

- **TestPyPI succeeded, PyPI failed.**  The tag is already on main.
  Use **Re-run jobs → only failed** in the workflow UI; the build
  artifact is still in the cache.  Don't retag — that fails uniqueness
  checks on TestPyPI.
- **PyPI succeeded but had a critical bug.**  Yank the release on the
  PyPI web UI (Releases → version → Options → Yank).  Bump to the next
  patch (`0.Y.(Z+1)`) and republish; yanked versions are not deleted,
  so users can still see they existed.
- **Version-drift sanity check fails.**  The `build` job aborts.
  Fix `pyproject.toml` ↔ `bioflow/__init__.py` mismatch, force-push
  the tag (`git tag -f vX.Y.Z && git push -f origin vX.Y.Z`) only if
  no publish step has run yet.  Otherwise bump to the next patch.

---

## Part 7 · Publishing to Bioconda

Most bioinformaticians install via conda/mamba, not pip, so a Bioconda
package widens reach substantially.  The recipe lives at
[`conda-recipe/meta.yaml`](https://github.com/hope9901/bioflow/blob/main/conda-recipe/meta.yaml); it is a
`noarch: python` package (the actual tools run as Docker containers, so
only bioflow's small pure-Python stack is a conda dependency).

**Prerequisite**: bioflowkit must already be live on **real PyPI** — the
recipe's `source.url` points at the PyPI sdist, and Bioconda's CI
downloads it.

Submission steps:

1. Get the sdist sha256 from PyPI:
   ```bash
   pip download bioflowkit==X.Y.Z --no-deps --no-binary :all: -d /tmp/bf
   sha256sum /tmp/bf/bioflowkit-X.Y.Z.tar.gz
   ```
2. Fork https://github.com/bioconda/bioconda-recipes and copy the recipe:
   ```bash
   mkdir -p recipes/bioflowkit
   cp <bioflow>/conda-recipe/meta.yaml recipes/bioflowkit/meta.yaml
   # paste the sha256 into the `source.sha256` field
   ```
3. (Optional) lint + build locally with the bioconda toolchain:
   ```bash
   conda install -c bioconda -c conda-forge bioconda-utils
   bioconda-utils lint recipes config.yml --packages bioflowkit
   bioconda-utils build recipes config.yml --packages bioflowkit
   ```
4. Open a PR to bioconda-recipes.  Their CI builds + tests it; once a
   maintainer merges, the package auto-publishes to the `bioconda`
   channel within ~an hour.

For subsequent version bumps Bioconda's auto-bump bot usually opens the
PR for you once the new PyPI release is detected — you just review and
merge.

---

## Part 8 · What this guide intentionally does NOT cover

These are out of scope for bioflow itself — use the right OS / cloud
primitive instead:

- HPC / SLURM scheduling
- Multi-user / quota / authentication
- Web dashboard for the scheduler
- Auto-execution of LLM suggestions
- Cross-machine workspace sync

bioflow stays a no-daemon Python SDK; only the OS scheduler (cron /
Task Scheduler) and Cowork are long-running, and each lives in its
own world.
