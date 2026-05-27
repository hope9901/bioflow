# Registry changelog

Every monthly Deep Research update appends an entry here after candidates
are benchmarked and approved.  See `docs/MAINTAINER.md` for the full
update workflow.

Prior versions of tool YAML files are never deleted — keeping old versions
allows reproducibility and rollback.

---

## 2026-05 — First freshness review (manual)

T1 daily check (`update/freshness_check.py`) ran for the first time
against the registry and surfaced:

- **2 yanked images** (no Docker Hub presence; private to fcyu account):
  - `fcyu/msfragger:4.1`  → marked `deprecated: true`, `replaced_by: comet`
  - `fcyu/fragpipe:22.0`  → marked `deprecated: true`, `replaced_by: comet`
  - `proteomics_dda` recipe rewritten on top of the open-source stack
    (msconvert → Comet → Percolator).  See commit history.
  - Added **`comet`** to `registry/tools/proteomics/`.

- **27 newer upstream tags** flagged for review.  Policy decision
  (this release): *retain current pins for stability.*  Each pin is
  understood to be a "compatibility anchor" — the bumped tag would
  require re-verifying every recipe's command_template against the
  upstream's possibly-breaking changes.  Future bumps will happen via
  the T3 monthly cycle once benchmark coverage matures.

  Tools with a meaningful reason to stay pinned should get an
  explicit ``pin_reason:`` field (added in the schema this release).

- **32 tags aged out** — upstream churn is healthy; not actionable.

<!-- Entries are added automatically by `bioflow update auto` -->
<!-- Format:
### YYYY-MM — <tool_id>
- **category**: <category>
- **replaces**: <old_tool_id or none>
- **benchmark**: "<measured result from paper>"
- **risk**: "<license / maintenance / known issues>"
-->
