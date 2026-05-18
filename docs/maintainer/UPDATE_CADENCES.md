# Registry update cadences

bioflow keeps the tool registry fresh through **five complementary
cadences**.  Each one targets a different decay mode, and they are
intentionally redundant — if Cowork stops firing, the daily check
notices.  If GitHub releases get missed, the monthly Deep Research
catches them.

| Tier | Cadence | Where it runs | What it does | Auto-promote? |
|---|---|---|---|---|
| **T1** | Daily 06:00 | Local cron / Task Scheduler | Image-tag freshness + yanked detection | ❌ report only |
| **T2** | Weekly 08:00 Mon | Local cron / Task Scheduler | GitHub release watch → candidate drafts | ✅ via T3 cron |
| **T3** | Monthly 02:30 day 1 | Local cron / Task Scheduler | Benchmark `update/candidates/**/*.yaml` → promote → git push | ✅ |
| **T4** | Quarterly 09:00 day 1 | Cowork scheduled task | Deep audit (deprecation, fork detection) → report | ❌ |
| **T5** | Event-driven | GitHub Actions on PR | Validate + smoke-test candidate YAMLs in a PR | ❌ posts comment |

Plus the existing **monthly Deep Research** (Cowork, 1st @ 09:00 KST)
that *feeds* T3 by emitting candidate YAMLs.

---

## T1 — Daily freshness check

**Script**: `update/freshness_check.py`
**Output**: `update/notifications/freshness-<YYYY-MM-DD>.md`
**Install**:

```powershell
# Windows
.\scripts\install-schedule-daily.ps1
```

```bash
# Linux / macOS
./scripts/install-schedule-cron-daily.sh
```

**Detects**:
- 🟢 **Newer upstream tags** for every registered image
  (queries quay.io / Docker Hub REST APIs)
- 🔴 **Yanked images** (upstream returned 404)
- 🟡 **Tag aged out** (current tag is older than the most recent 25 on
  the registry)
- ⚠️  **Cowork silence** — if no candidate YAMLs have landed under
  `update/candidates/` for >35 days, the off-machine scheduler may
  have stopped firing.

**Exit codes**: 0 = clean · 1 = newer tags available · 2 = yanked
images found.  Wire your cron to mail on non-zero.

---

## T2 — Weekly release watch

**Script**: `update/release_watch.py`
**Requires**: tool YAMLs to declare `source_repo: <owner>/<repo>`
**Output**: candidate YAML draft → `update/candidates/<YYYY-MM>/`
**State**: `update/release_watch_state.json` (so the same release is
never filed twice)
**Install**:

```powershell
.\scripts\install-schedule-weekly.ps1
```

```bash
./scripts/install-schedule-cron-weekly.sh
```

Set `GITHUB_TOKEN` env var to lift the API rate limit from 60/hr →
5000/hr.

The candidate it writes is a near-copy of the original YAML with
`version:` bumped and the image tag rewritten **best-effort** (the
BioContainers build usually lags GitHub by a few days).  An
`update_meta.note` warns the reviewer to confirm the image tag before
merge.

---

## T3 — Monthly benchmark + promote *(existing)*

See the main `docs/MAINTAINER.md` — this is the unchanged cron that
runs `bioflow update auto --auto-approve --git-push` on the 1st of
every month.

---

## T4 — Quarterly deep audit

**Where**: Cowork scheduled task
**Prompt**: `docs/maintainer/quarterly_audit_prompt.md`
**Schedule**: `0 9 1 */3 *` (1st of Jan / Apr / Jul / Oct, 09:00 KST)
**Output**: chat report listing deprecation candidates — no PR
(human decides)

Looks for:
- Tools whose upstream had no commits in 18+ months
- Citation count flat-lining or dropping
- A new fork / successor with traction (≥2× stars in the last year)
- Container image not refreshed since 2020

The maintainer reviews and decides whether to deprecate / replace.

---

## T5 — PR-triggered smoke test

**Where**: GitHub Actions (`.github/workflows/candidate-smoke-test.yml`)
**Trigger**: any PR that adds/edits files under `update/candidates/**`
**What it does**:

1. Computes which candidate dirs the PR touched
2. Runs `bioflow update auto --candidates-dir <each>` (mock backend by
   default — set the `BIOFLOW_REAL_DOCKER=1` repo secret to enable real
   image pulls)
3. Uploads the per-candidate JSON report as a workflow artifact
4. Comments a Markdown summary on the PR

No automatic merge — the maintainer still has to approve.

---

## Why five cadences and not one?

Each cadence covers a different failure mode the others miss:

|                      | T1 daily | T2 weekly | T3 monthly | T4 quarterly | T5 PR |
|---|:---:|:---:|:---:|:---:|:---:|
| Image yanked by upstream | ✅ | | | | |
| Upstream minor release   |    | ✅ | (✅ via Deep Research) | | |
| Whole new tool to add    |    |    | ✅ (Deep Research) | | |
| Deprecation / abandonment|    |    |    | ✅ | |
| Broken candidate YAML    |    |    | (caught in benchmark) | | ✅ |
| Pull-time CVE            | (add Trivy as a follow-up) | | | | |

If any single cadence fails (cron stopped, Cowork down, GitHub API
throttle), the redundancy across the other tiers keeps the registry
moving.
