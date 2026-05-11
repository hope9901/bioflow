# Maintainer guide

> **Audience**: the single person who owns the GitHub repo and pushes
> registry updates.  Researchers using bioflow as a tool don't need
> anything in this file — they just `git pull`.

The registry of tool YAMLs evolves over time as new bioinformatics
software ships.  bioflow's design intentionally splits the update work
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
5. With `--git-push`:
   - `git add registry/ update/CHANGELOG.md update/last_run.json`
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

---

## Part 5 · What this guide intentionally does NOT cover

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
