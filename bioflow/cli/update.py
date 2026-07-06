"""`bioflow update` — registry update / approve workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import REGISTRY_DEFAULT, app


def _regenerate_registry_artifacts(repo_root: Path) -> None:
    """Regenerate registry-derived artifacts after an auto-approval bumped the
    registry, so the freshness CI gates stay green when the auto-run pushes:

      * ``registry/io_contracts.json`` — the per-tool I/O format contract
        snapshot.  A version bump that changes a tool's input/output formats is
        exactly the drift the ``io-contracts`` gate flags, so the snapshot must
        be re-blessed in the same commit as the bump.
      * ``README.md`` + ``docs/reference/*.md`` — the generated tool/recipe
        tables (docs-fresh gate).

    Best effort: a failure is surfaced but does not abort the run — the commit
    then trips the CI gate, which is the intended safety net.
    """
    import subprocess as _sub  # noqa: PLC0415
    import sys as _sys  # noqa: PLC0415

    for script, arg in (("io_contracts.py", "update"), ("gen_docs.py", None)):
        cmd = [_sys.executable, str(repo_root / "scripts" / script)]
        if arg:
            cmd.append(arg)
        try:
            _sub.run(cmd, cwd=str(repo_root), check=True,
                     capture_output=True, text=True)
            rprint(f"[green]✓ regenerated[/] via scripts/{script}")
        except (_sub.CalledProcessError, FileNotFoundError) as exc:
            rprint(f"[yellow]⚠ scripts/{script} failed[/] "
                   f"(the CI freshness gate will catch it): {exc}")


@app.command("update")
def update_cmd(
    action: str = typer.Argument(..., help="approve | auto"),
    candidate: Optional[Path] = typer.Option(
        None, "--candidate", "-c",
        help="Path to a single candidate YAML to approve.",
    ),
    candidates_dir: Optional[Path] = typer.Option(
        None, "--candidates-dir",
        help="Approve every .yaml in this directory.",
    ),
    registry_dir: Path = typer.Option(
        REGISTRY_DEFAULT, "--registry",
        help="Root of the tool registry.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing entries."),
    delete_candidate: bool = typer.Option(
        False, "--delete-candidate",
        help="Delete candidate file(s) after successful approval.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen without writing."),
    # `auto` action specific
    auto_approve: bool = typer.Option(
        False, "--auto-approve",
        help="[auto] Approve any candidate whose smoke test passes (off by default — "
             "the safe scheduled mode only benchmarks + reports).",
    ),
    report_path: Optional[Path] = typer.Option(
        None, "--report",
        help="[auto] Write a JSON summary to this path (default: "
             "update/last_run.json).",
    ),
    use_real_docker: bool = typer.Option(
        False, "--real",
        help="[auto] Run smoke tests with the real DockerBackend (slow, "
             "but the only way to catch image-pull / runtime failures).",
    ),
    git_commit: bool = typer.Option(
        False, "--git-commit",
        help="[auto, maintainer-only] After approval, `git add` the "
             "registry / CHANGELOG / report and `git commit` if anything "
             "changed.  Off by default.",
    ),
    git_push: bool = typer.Option(
        False, "--git-push",
        help="[auto, maintainer-only] `git push origin <branch>` after the "
             "commit.  Implies --git-commit.  Off by default — only the "
             "repository maintainer should set this on their scheduled task.",
    ),
    git_remote: str = typer.Option(
        "origin", "--git-remote",
        help="[auto] Remote name for --git-push.",
    ),
    git_branch: Optional[str] = typer.Option(
        None, "--git-branch",
        help="[auto] Branch to push.  Defaults to the current HEAD.",
    ),
) -> None:
    """Registry update utilities.

    \b
    approve   Promote a candidate YAML (or a whole directory) to the registry.
    auto      Scheduled pipeline: benchmark every YAML in update/candidates/,
              write a JSON report, and (with --auto-approve) promote passes.
              Designed to be wired into Windows Task Scheduler / cron — see
              scripts/install-schedule-windows.ps1 and
              scripts/install-schedule-cron.sh.
    """
    from bioflow.core.approve import (  # noqa: PLC0415
        ApprovalError,
        approve_all_candidates,
        approve_candidate,
    )

    if action == "approve":
        if candidate and candidates_dir:
            rprint("[red]Specify --candidate OR --candidates-dir, not both.[/]")
            raise typer.Exit(code=1)

        if candidate:
            if dry_run:
                rprint(f"[dim][DRY RUN] Would approve {candidate}[/]")
            try:
                dest = approve_candidate(
                    candidate,
                    registry_dir=registry_dir,
                    overwrite=overwrite,
                    delete_candidate=delete_candidate,
                    dry_run=dry_run,
                )
                if not dry_run:
                    rprint(f"[green]✓ Approved:[/] {candidate.name} → [cyan]{dest}[/]")
                else:
                    rprint(f"[dim]Would write → {dest}[/]")
            except ApprovalError as exc:
                rprint(f"[red]Approval failed:[/] {exc}")
                raise typer.Exit(code=1)

        elif candidates_dir:
            if not candidates_dir.is_dir():
                rprint(f"[red]Not a directory:[/] {candidates_dir}")
                raise typer.Exit(code=1)
            results = approve_all_candidates(
                candidates_dir,
                registry_dir=registry_dir,
                overwrite=overwrite,
                delete_candidates=delete_candidate,
                dry_run=dry_run,
            )
            if not results:
                rprint("[yellow]No candidate YAML files found.[/]")
                raise typer.Exit(code=0)

            approved = [r for r in results if r["status"] == "approved"]
            skipped  = [r for r in results if r["status"] == "skipped"]
            errors   = [r for r in results if r["status"] == "error"]

            for r in approved:
                rprint(f"[green]✓ approved[/]  {r['file']} → {r.get('dest','')}")
            for r in skipped:
                rprint(f"[yellow]⚠ skipped[/]   {r['file']}: {r.get('error','')}")
            for r in errors:
                rprint(f"[red]✗ error[/]     {r['file']}: {r.get('error','')}")

            rprint(
                f"\n[bold]Total:[/] {len(results)}  "
                f"[green]approved={len(approved)}[/]  "
                f"[yellow]skipped={len(skipped)}[/]  "
                f"[red]errors={len(errors)}[/]"
            )
            if errors:
                raise typer.Exit(code=1)
        else:
            rprint("[red]--candidate or --candidates-dir is required for 'approve'.[/]")
            raise typer.Exit(code=1)

    elif action == "auto":
        # Unattended pipeline for OS-level schedulers (Task Scheduler / cron)
        import datetime as _dt  # noqa: PLC0415
        import json  # noqa: PLC0415
        from update import benchmark as _b  # noqa: PLC0415

        # Walk every */ subdir under update/candidates/ — Deep Research
        # drops monthly batches under update/candidates/<YYYY-MM>/
        root_dirs: list[Path] = (
            [candidates_dir] if candidates_dir is not None
            else [Path("update/candidates")]
        )
        all_paths: list = []
        for root in root_dirs:
            if not root.exists():
                continue
            all_paths.extend(sorted(root.rglob("*.yaml")))

        if not all_paths:
            rprint("[yellow]No candidate YAML files found under "
                   f"{root_dirs[0]}.[/]")
            raise typer.Exit(code=0)

        rprint(f"[bold]Found {len(all_paths)} candidate(s):[/]")
        results = []
        for p in all_paths:
            rprint(f"  • {p}")
        rprint()

        for p in all_paths:
            try:
                br = _b.smoke_test(p, use_real_docker=use_real_docker)
            except Exception as exc:
                rprint(f"[red]✗ {p.name}:[/] {exc}")
                results.append({
                    "candidate": str(p), "passed": False, "skipped": False,
                    "error": str(exc), "elapsed_s": 0.0,
                })
                continue
            if br.skipped:
                mark = "[yellow]⊘[/]"
                note = br.skip_reason
            elif br.passed:
                mark = "[green]✓[/]"
                note = ""
            else:
                mark = "[red]✗[/]"
                note = br.error or ""
            rprint(f"  {mark} {p.name:<40s}  {br.elapsed:>5.1f}s  {note}")
            results.append({
                "candidate":  str(p),
                "passed":     br.passed,
                "skipped":    br.skipped,
                "skip_reason": br.skip_reason,
                "error":      br.error,
                "elapsed_s":  br.elapsed,
            })

        n_pass = sum(1 for r in results if r["passed"])
        n_fail = len(results) - n_pass
        rprint(f"\n[bold]Total:[/] {len(results)}  "
               f"[green]passed={n_pass}[/]  [red]failed={n_fail}[/]")

        # Write JSON report
        target = report_path or Path("update") / "last_run.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({
                "ran_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "candidates_scanned": len(results),
                "passed": n_pass,
                "failed": n_fail,
                "real_docker": use_real_docker,
                "auto_approve": auto_approve,
                "results": results,
            }, indent=2),
            encoding="utf-8",
        )
        rprint(f"[dim]Report → {target}[/]")

        # Optionally auto-approve passing candidates
        n_approved = 0
        if auto_approve and n_pass > 0:
            rprint(f"\n[bold]Auto-approving {n_pass} passing candidate(s) "
                   "→ registry[/]")
            from bioflow.core.approve import (  # noqa: PLC0415
                approve_candidate, ApprovalError,
            )
            for r in results:
                if not r["passed"]:
                    continue
                try:
                    dest = approve_candidate(
                        Path(r["candidate"]),
                        registry_dir=registry_dir,
                        overwrite=False,
                        delete_candidate=delete_candidate,
                        dry_run=dry_run,
                    )
                    rprint(f"  [green]✓ approved[/]  "
                           f"{Path(r['candidate']).name} → {dest}")
                    n_approved += 1
                except ApprovalError as exc:
                    rprint(f"  [yellow]⚠ skipped[/]  "
                           f"{Path(r['candidate']).name}: {exc}")

        # Re-bless registry-derived artifacts (I/O contract snapshot + generated
        # docs) so a scheduled auto-bump stays in lockstep with the freshness CI
        # gates (io-contracts, docs-fresh) when it commits/pushes.  Only when an
        # approval actually changed the registry, and only against the real
        # project registry (tests use a tmp registry_dir and must not touch it).
        _repo_root = Path(__file__).resolve().parents[2]
        if (n_approved and not dry_run
                and registry_dir.resolve() == (_repo_root / "registry")):
            _regenerate_registry_artifacts(_repo_root)

        # ── Maintainer-only: commit + push to GitHub ────────────────────
        if (git_commit or git_push) and not dry_run:
            from datetime import date as _date  # noqa: PLC0415
            import subprocess as _sub  # noqa: PLC0415

            def _git(*args, check=True):
                """Run git in the repo root.  Returns CompletedProcess."""
                return _sub.run(
                    ["git", *args],
                    capture_output=True, text=True, check=check,
                )

            # Stage everything relevant.  registry_dir already covers
            # registry/io_contracts.json; README + docs/reference carry the
            # regenerated tool/recipe tables.
            try:
                _git("add",
                     str(registry_dir),
                     "update/CHANGELOG.md",
                     "README.md",
                     "docs/reference",
                     str(report_path or Path("update") / "last_run.json"))
            except (FileNotFoundError, _sub.CalledProcessError) as exc:
                rprint(f"[red]git add failed:[/] {exc}")
                raise typer.Exit(code=1)

            # Skip commit if there's nothing staged
            staged = _git("diff", "--cached", "--quiet", check=False)
            if staged.returncode == 0:
                rprint("[dim]No staged changes — skipping git commit.[/]")
            else:
                today = _date.today().isoformat()
                msg = (
                    f"chore(registry): monthly auto-update {today} — "
                    f"{n_approved} new tool(s)"
                )
                try:
                    _git("commit", "-m", msg)
                    rprint(f"[green]✓ git commit:[/] {msg}")
                except _sub.CalledProcessError as exc:
                    rprint(f"[red]git commit failed:[/]\n{exc.stderr}")
                    raise typer.Exit(code=1)

                if git_push:
                    branch = git_branch
                    if branch is None:
                        # Resolve current HEAD branch
                        head = _git("rev-parse", "--abbrev-ref", "HEAD",
                                    check=False)
                        branch = head.stdout.strip() or "main"
                    try:
                        push = _git("push", git_remote, branch)
                        rprint(
                            f"[green]✓ git push:[/] {git_remote}/{branch}"
                        )
                        if push.stderr.strip():
                            rprint(f"[dim]{push.stderr.strip()}[/]")
                    except _sub.CalledProcessError as exc:
                        rprint(f"[red]git push failed:[/]\n{exc.stderr}")
                        raise typer.Exit(code=1)

        if n_fail:
            raise typer.Exit(code=1)

    else:
        rprint(f"[red]Unknown action '{action}'.[/] Available: approve | auto")
        raise typer.Exit(code=1)


