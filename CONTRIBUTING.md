# Contributing to bioflow

Thank you for considering a contribution to bioflow.  The project is maintained
by a single person; please read this document before opening a PR.

---

## What belongs in bioflow

bioflow is intentionally scoped to **one workstation + local Docker**.
The following are **explicitly out of scope** and PRs for them will be closed:

- HPC / SLURM / Kubernetes backends
- Multi-user authentication or quota management
- WDL / CWL / Nextflow compatibility
- Web UI or dashboard
- Automatic LLM code execution

If you are unsure whether your idea fits, open an issue first.

---

## How to contribute

### Bug reports

1. Search existing issues before opening a new one.
2. Include: OS, Python version, Docker version, the exact command, and the
   full error output.

### Feature requests

Open an issue with the label `enhancement`.  Describe the use-case, not just
the solution.

### Pull requests

1. Fork and create a feature branch from `main`.
2. Install the dev dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
3. Run the full unit-test suite before committing:
   ```bash
   python -m pytest tests/unit -q
   ```
4. Keep commits focused.  One logical change per PR.
5. Update `CHANGELOG.md` under `[Unreleased]`.
6. Open the PR and fill in the template.

### Tool-registry additions

New tools live in `registry/tools/<category>/<id>.yaml`.  They must:

- Pass `registry/schema.yaml` validation.
- Have a publicly pullable container image (BioContainers / staphb / quay.io
  preferred).
- Include a `citation` with DOI or PMID.

Run the smoke test before submitting:

```bash
bioflow update auto --candidates-dir <your-yaml-dir>
```

---

## Code style

- **Python**: [ruff](https://docs.astral.sh/ruff/) (`ruff check .`)
- **Line length**: 100
- **Type hints**: encouraged for public API

---

## Commit messages

```
<type>(<scope>): <short summary>

# Types: feat, fix, docs, refactor, test, chore
# Examples:
feat(sdk): add parallel=auto to @stage decorator
fix(runner): handle CRLF in docker exec output
docs(readme): update install instructions
```

---

## License

By contributing you agree that your contribution will be licensed under the
[MIT License](LICENSE) that covers this project.
