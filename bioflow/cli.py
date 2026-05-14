"""bioflow CLI entry point.

Subcommands (MVP scope):
  bioflow hw            Show detected hardware profile.
  bioflow tools         List tools available on this host (filtered by hw).
  bioflow recommend     Run a preset pipeline.
  bioflow custom        Interactively build a pipeline from compatible tools.
  bioflow run           Execute a pipeline config file.
  bioflow db            Fetch / manage reference databases.
  bioflow update        Run the monthly registry update workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console

# ── Windows-safe console encoding ───────────────────────────────────────────
# On non-UTF-8 Windows shells (e.g. Korean cp949) Rich's ✓/✗/⚠ glyphs raise
# UnicodeEncodeError mid-print and abort the command.  Force stdout/stderr to
# UTF-8 when the interpreter supports it (Python ≥ 3.7) — this is a no-op on
# already-UTF-8 terminals and keeps non-Windows behaviour unchanged.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="bioflow: genome assembly/annotation & RNA-seq DEG pipeline platform.",
)
# Rich Console: keep colour but degrade glyphs gracefully on legacy code pages
console = Console(emoji=False, legacy_windows=False)


@app.command("hw")
def hw_cmd() -> None:
    """Detect and print hardware profile (CPU / RAM / GPU / disk / arch)."""
    from bioflow.core.hardware import detect

    profile = detect()
    rprint(profile.model_dump())


@app.command("tools")
def tools_cmd(
    registry_dir: Path = typer.Option(
        Path("registry"),
        "--registry",
        "-r",
        help="Path to tool registry directory.",
    ),
    category: Optional[str] = typer.Option(None, "--category", "-c"),
    recommend: Optional[str] = typer.Option(
        None, "--recommend",
        help="Score and rank presets for this pipeline on the current host "
             "(genome_assembly | rnaseq_deg).",
    ),
) -> None:
    """List tools available on this host, classified by hardware compatibility."""
    from bioflow.core.compatibility import classify, recommend_presets
    from bioflow.core.hardware import detect
    from bioflow.core.registry import load_registry

    hw = detect()
    tools = load_registry(registry_dir)

    if recommend:
        recs = recommend_presets(tools, hw, recommend, registry_dir=registry_dir)
        if not recs:
            console.print(f"[yellow]No presets found for pipeline '{recommend}'[/]")
            return
        console.print(f"\n[bold]Preset recommendations for [cyan]{recommend}[/] on this host:[/]\n")
        for r in recs:
            runnable_tag = "[green]✓ runnable[/]" if r["runnable"] else "[red]✗ incompatible tools[/]"
            score_color = "green" if r["score"] >= 80 else "yellow" if r["score"] >= 50 else "red"
            console.print(
                f"  [{score_color}]{r['score']:3d}[/]  [bold]{r['preset']}[/]  {runnable_tag}"
            )
            if r["applies_to"]:
                at = r["applies_to"]
                console.print(
                    f"       species={at.get('species',[])}  "
                    f"read_type={at.get('read_type',[])}  "
                    f"mode={at.get('mode',[])}"
                )
            if r["incompatible_tools"]:
                console.print(
                    f"       [red]incompatible:[/] {', '.join(r['incompatible_tools'])}"
                )
            if r["slow_tools"]:
                console.print(
                    f"       [yellow]slow:[/] {', '.join(r['slow_tools'])}"
                )
        return

    if category:
        tools = [t for t in tools if t.category == category]
    classified = classify(tools, hw)
    for status, bucket in classified.items():
        color = {"installable": "green", "runnable_slow": "yellow", "incompatible": "red"}[status]
        console.print(f"\n[bold {color}]{status}[/] ({len(bucket)} tools)")
        for t in bucket:
            console.print(f"  - {t.id}  [{t.category}]  image={t.container.image}")


@app.command("recommend")
def recommend_cmd(
    preset: str = typer.Option(..., "--preset", "-p"),
    config: Path = typer.Option(..., "--config", "-c", exists=True),
    registry: Path = typer.Option(Path("registry"), "--registry", "-r"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan without executing."),
) -> None:
    """Run a preset (recommended) pipeline against an input config."""
    import yaml  # noqa: PLC0415

    from bioflow.core.compatibility import classify  # noqa: PLC0415
    from bioflow.core.hardware import detect  # noqa: PLC0415
    from bioflow.core.planner import plan_from_preset  # noqa: PLC0415
    from bioflow.core.registry import load_registry  # noqa: PLC0415
    from bioflow.core.runner import run_plan  # noqa: PLC0415

    # Resolve registry_dir from config file (may override --registry)
    with config.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    reg_dir = Path(raw.get("registry_dir", str(registry)))

    # Hardware + compatibility summary
    hw = detect()
    tools = load_registry(reg_dir)
    classified = classify(tools, hw)
    slow = classified["runnable_slow"]
    bad  = classified["incompatible"]
    if bad:
        console.print(
            f"[red]⚠  {len(bad)} tool(s) incompatible with this host:[/] "
            + ", ".join(t.id for t in bad)
        )
    if slow:
        console.print(
            f"[yellow]⚡ {len(slow)} tool(s) may run slowly on this host:[/] "
            + ", ".join(t.id for t in slow)
        )

    execution_plan = plan_from_preset(preset, config)

    if dry_run:
        console.print("\n[bold]Execution plan (dry-run):[/]")
        for s in execution_plan.stages:
            console.print(f"  {s.stage_id}  →  [cyan]{s.tool_id}[/]")
        return

    run_plan(execution_plan)


@app.command("custom")
def custom_cmd(
    pipeline: str = typer.Option(..., "--pipeline", help="genome_assembly | rnaseq_deg"),
    out: Path = typer.Option(Path("custom_config.yaml"), "--out", "-o"),
    registry: Path = typer.Option(Path("registry"), "--registry", "-r"),
) -> None:
    """Interactively pick tools per stage (only hardware-compatible ones shown)."""
    from bioflow.core.planner import interactive_build  # noqa: PLC0415

    interactive_build(pipeline, out, registry_dir=registry)
    rprint(f"[green]✓ Saved custom pipeline config →[/] {out}")


@app.command("run")
def run_cmd(config: Path = typer.Argument(..., exists=True)) -> None:
    """Execute a saved pipeline config file."""
    from bioflow.core.planner import plan_from_config
    from bioflow.core.runner import run_plan

    execution_plan = plan_from_config(config)
    run_plan(execution_plan)


@app.command("db")
def db_cmd(
    action: str = typer.Argument(..., help="fetch | list | verify"),
    name: Optional[str] = typer.Argument(None, help="Database key (see 'bioflow db list')."),
    dest: Path = typer.Option(
        Path("data/references"),
        "--dest", "-d",
        help="Root directory for downloaded databases.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Re-download even if file exists."),
) -> None:
    """Fetch or verify reference databases (eggNOG / Pfam / Dfam / BUSCO / UniProt)."""
    from bioflow.core.db import fetch_db, list_dbs, verify_db  # noqa: PLC0415

    if action == "list":
        rows = list_dbs()
        console.print("\n[bold]Available reference databases:[/]\n")
        for r in rows:
            used = ", ".join(r["used_by"])
            console.print(
                f"  [cyan]{r['key']:<20}[/]  {r['size_gb']:5.1f} GB  "
                f"used by: {used}"
            )
            console.print(f"    {r['name']}")
            if r["notes"]:
                console.print(f"    [dim]{r['notes']}[/]")
        return

    if not name:
        rprint("[red]Error:[/] 'name' argument required for fetch/verify.")
        raise typer.Exit(code=1)

    if action == "fetch":
        try:
            path = fetch_db(name, dest, skip_if_exists=not force)
            rprint(f"[green]✓[/] {name} → {path}")
        except (KeyError, RuntimeError) as exc:
            rprint(f"[red]Error:[/] {exc}")
            raise typer.Exit(code=1) from exc

    elif action == "verify":
        try:
            ok = verify_db(name, dest)
            if ok:
                rprint(f"[green]✓[/] {name} — OK")
            else:
                rprint(f"[red]✗[/] {name} — FAILED or missing")
                raise typer.Exit(code=1)
        except KeyError as exc:
            rprint(f"[red]Error:[/] {exc}")
            raise typer.Exit(code=1) from exc

    else:
        rprint(f"[red]Unknown action '{action}'.[/] Use: fetch | list | verify")
        raise typer.Exit(code=1)


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
        Path("registry"), "--registry",
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
        root_dirs = [candidates_dir] if candidates_dir else [
            Path("update/candidates"),
        ]
        all_paths: list = []
        for r in root_dirs:
            if not r.exists():
                continue
            all_paths.extend(sorted(r.rglob("*.yaml")))

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

            # Stage everything relevant
            try:
                _git("add",
                     str(registry_dir),
                     "update/CHANGELOG.md",
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


@app.command("ncbi")
def ncbi_cmd(
    action: str = typer.Argument(..., help="search | genome | protein"),
    taxon: str = typer.Option(..., "--taxon", "-t",
        help="Scientific name or NCBI taxonomy ID (e.g. 'dickeya', '2038')."),
    db: str = typer.Option("genome", "--db",
        help="[search only] Database to query: genome | protein."),
    out: Optional[Path] = typer.Option(None, "--out", "-o",
        help="Output directory for downloaded files."),
    level: Optional[str] = typer.Option(None, "--level", "-l",
        help="[genome] Assembly level filter: complete | chromosome | scaffold | contig."),
    reference_only: bool = typer.Option(False, "--reference-only",
        help="[genome] Return only reference/representative assemblies."),
    max: int = typer.Option(20, "--max", "-n",
        help="Maximum number of assemblies (genome) or sequences (protein) to retrieve."),
    include: str = typer.Option("GENOME_FASTA", "--include",
        help="[genome download] Comma-separated data types: "
             "GENOME_FASTA, GENOME_GFF, PROT_FASTA, CDS_FASTA, RNA_FASTA, "
             "GENOME_GBFF, SEQUENCE_REPORT.  PROTEIN_FASTA is accepted as an "
             "alias of PROT_FASTA."),
    filter_term: str = typer.Option("refseq[filter]", "--filter",
        help="[protein] Entrez filter.  Use '' for all records."),
) -> None:
    """Download genomes and proteins from NCBI.

    \b
    search   List available assemblies or proteins for a taxon (no download).
    genome   Download genome FASTA (and optionally GFF/protein) files.
    protein  Download protein FASTA for annotation evidence (BRAKER3/MAKER).

    \b
    Examples:
      bioflow ncbi search  --taxon dickeya --db genome --level complete
      bioflow ncbi genome  --taxon dickeya --out /data/genomes --level complete --max 20
      bioflow ncbi protein --taxon pectobacteriaceae --out /data/proteins --max 2000
    """
    from bioflow.core.ncbi import (  # noqa: PLC0415
        NcbiError, download_genomes, download_proteins,
        list_genomes, list_proteins,
    )

    # ------------------------------------------------------------------ search
    if action == "search":
        if db == "genome":
            try:
                assemblies = list_genomes(
                    taxon,
                    assembly_level=level,
                    reference_only=reference_only,
                    max_results=max,
                )
            except NcbiError as exc:
                rprint(f"[red]NCBI error:[/] {exc}")
                raise typer.Exit(code=1)

            if not assemblies:
                rprint(f"[yellow]No genome assemblies found for '{taxon}'.[/]")
                raise typer.Exit(code=0)

            rprint(f"\n[bold]Genome assemblies for [cyan]{taxon}[/] — {len(assemblies)} result(s)[/]\n")
            for a in assemblies:
                ref_tag = " [bold green][REF][/]" if a.is_reference else ""
                size_mb = a.total_sequence_length / 1_000_000
                rprint(
                    f"  [cyan]{a.accession}[/]  "
                    f"{a.organism}"
                    + (f" ({a.strain})" if a.strain else "")
                    + f"  [dim]{a.assembly_level}[/]  {size_mb:.1f} Mb"
                    + ref_tag
                )

        elif db == "protein":
            try:
                total, records = list_proteins(
                    taxon, filter_term=filter_term, preview_size=max
                )
            except NcbiError as exc:
                rprint(f"[red]NCBI error:[/] {exc}")
                raise typer.Exit(code=1)

            if total == 0:
                rprint(f"[yellow]No proteins found for '{taxon}'.[/]")
                raise typer.Exit(code=0)

            rprint(
                f"\n[bold]Proteins for [cyan]{taxon}[/] — "
                f"{total} total (showing {len(records)})[/]\n"
            )
            for r in records:
                rprint(
                    f"  [dim]{r['uid']}[/]  {r['organism']}  "
                    f"[dim]{r['length']} aa[/]  {r['title'][:70]}"
                )
        else:
            rprint(f"[red]Unknown --db '{db}'.[/] Use: genome | protein")
            raise typer.Exit(code=1)

    # ------------------------------------------------------------------ genome
    elif action == "genome":
        if out is None:
            rprint("[red]--out is required for 'genome' download.[/]")
            raise typer.Exit(code=1)

        include_types = [s.strip().upper() for s in include.split(",")]
        rprint(
            f"\n[bold]Downloading genomes for [cyan]{taxon}[/] "
            f"(max {max}, level={level or 'any'}, include={include_types})[/]\n"
        )
        try:
            paths = download_genomes(
                taxon, out,
                assembly_level=level,
                reference_only=reference_only,
                max_assemblies=max,
                include=include_types,
            )
        except NcbiError as exc:
            rprint(f"[red]Download failed:[/] {exc}")
            raise typer.Exit(code=1)

        rprint(f"\n[green]✓ {len(paths)} file(s) downloaded → {out}[/]")
        for p in paths:
            rprint(f"  [dim]{p.name}[/]")

    # ------------------------------------------------------------------ protein
    elif action == "protein":
        if out is None:
            rprint("[red]--out is required for 'protein' download.[/]")
            raise typer.Exit(code=1)

        rprint(
            f"\n[bold]Downloading proteins for [cyan]{taxon}[/] "
            f"(max {max}, filter={filter_term!r})[/]\n"
        )
        try:
            fasta_path = download_proteins(
                taxon, out,
                filter_term=filter_term,
                max_results=max,
            )
        except NcbiError as exc:
            rprint(f"[red]Download failed:[/] {exc}")
            raise typer.Exit(code=1)

        rprint(f"\n[green]✓ Protein FASTA → {fasta_path}[/]")

    else:
        rprint(f"[red]Unknown action '{action}'.[/] Available: search | genome | protein")
        raise typer.Exit(code=1)


def _parse_recipe_extra(extra: "list[str]") -> "dict[str, object]":
    """Parse pass-through ``--key value`` / ``--key=value`` / ``--flag``
    tokens (collected by Click's ``ignore_unknown_options``) into a
    kwargs dict.

    ``--sample-id`` becomes ``sample_id``.  Pure-integer values are
    coerced to ``int`` so recipes doing arithmetic on numeric options
    (e.g. ``cb_len + 1``) keep working; everything else stays a string
    and recipes coerce to ``Path`` themselves.
    """
    out: "dict[str, object]" = {}
    i = 0
    while i < len(extra):
        tok = extra[i]
        if not tok.startswith("--"):
            i += 1
            continue
        body = tok[2:]
        if "=" in body:
            key, val = body.split("=", 1)
            out[key.replace("-", "_")] = val
            i += 1
        elif i + 1 < len(extra) and not extra[i + 1].startswith("--"):
            out[body.replace("-", "_")] = extra[i + 1]
            i += 2
        else:
            out[body.replace("-", "_")] = "true"   # bare flag
            i += 1
    # light numeric coercion — paths never look like pure integers
    for k, v in list(out.items()):
        if isinstance(v, str) and v.isdigit():
            out[k] = int(v)
    return out


@app.command(
    "recipe",
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)
def recipe_cmd(
    ctx: typer.Context,
    action: str = typer.Argument(
        ..., help="list | show <name> | run <name>"
    ),
    name: Optional[str] = typer.Argument(None, help="Recipe name."),
    out: Path = typer.Option(
        Path("bioflow_recipe_out"),
        "--out", "-o",
        help="Output workspace (created if missing).",
    ),
    taxon: Optional[str] = typer.Option(None, "--taxon", "-t",
        help="NCBI taxon (for taxon-driven recipes)."),
    max_genomes: int = typer.Option(30, "--max", "-n",
        help="Cap on assemblies to fetch."),
    reference_only: bool = typer.Option(True, "--reference-only/--all",
        help="Use only RefSeq reference assemblies."),
    identity: int = typer.Option(90, "--identity",
        help="Identity threshold (recipe-specific; e.g. Roary -i)."),
    genome_dir: Optional[Path] = typer.Option(None, "--genome-dir",
        help="Directory of *.fna inputs (ani_matrix, amr_vf_catalogue)."),
    gff_dir: Optional[Path] = typer.Option(None, "--gff-dir",
        help="Directory of Prokka GFF inputs (phylogeny)."),
    traits_csv: Optional[Path] = typer.Option(None, "--traits-csv",
        help="Scoary-format binary traits CSV (gwas)."),
    gpa_csv: Optional[Path] = typer.Option(None, "--gpa-csv",
        help="Roary gene_presence_absence.csv (gwas, phylogeny fallback, cog_enrichment)."),
    tree: Optional[Path] = typer.Option(None, "--tree",
        help="Ultrametric Newick tree (cafe_evolution)."),
    count_table: Optional[Path] = typer.Option(None, "--count-table",
        help="CAFE-format family count matrix (cafe_evolution)."),
    pangenome_faa: Optional[Path] = typer.Option(None, "--pangenome-faa",
        help="One protein per Roary cluster (cog_enrichment)."),
    cog_faa: Optional[Path] = typer.Option(None, "--cog-faa",
        help="COG-2024 reference FASTA (cog_enrichment)."),
    cog_def: Optional[Path] = typer.Option(None, "--cog-def",
        help="NCBI cog-24.def.tab (cog_enrichment)."),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Print the DAG without running."),
) -> None:
    """Curated end-to-end pipelines (the Tier-B entry point).

    \b
    Examples:
      bioflow recipe list
      bioflow recipe show pangenome
      bioflow recipe run pangenome --taxon Dickeya --max 13
      bioflow recipe run pangenome --taxon Pectobacterium --dry-run
    """
    from bioflow import recipes  # noqa: PLC0415  — lazy import
    from bioflow.sdk import set_workspace  # noqa: PLC0415

    if action == "list":
        if not recipes.names():
            rprint("[yellow]No recipes registered.[/]")
            raise typer.Exit(code=0)
        console.print("\n[bold]Available recipes:[/]\n")
        for n in recipes.names():
            p = recipes.get(n)
            console.print(
                f"  [cyan]{n:<20s}[/] [dim]({len(p.stages)} stages)[/]  "
                f"{p.description}"
            )
        return

    if not name:
        rprint(f"[red]'{action}' requires a recipe name.[/]")
        raise typer.Exit(code=1)

    try:
        pipe = recipes.get(name)
    except KeyError as exc:
        rprint(f"[red]{exc}[/]")
        raise typer.Exit(code=1)

    if action == "show":
        pipe.show_graph()
        return

    if action == "run":
        if dry_run:
            rprint(f"\n[bold]Dry-run for recipe[/] [cyan]{name}[/]:\n")
            pipe.show_graph()
            return

        out = out.resolve()
        out.mkdir(parents=True, exist_ok=True)
        set_workspace(out)
        rprint(f"\n[bold]Running recipe[/] [cyan]{name}[/]  workspace=[dim]{out}[/]")

        # Build kwargs intelligently — pass only what the pipeline accepts.
        # Explicit options below cover the comparative-genomics recipes;
        # any other recipe's parameters arrive as pass-through --key value
        # tokens parsed from ctx.args.
        import inspect  # noqa: PLC0415
        sig = inspect.signature(pipe.func)
        candidate: "dict[str, object]" = {
            "taxon": taxon,
            "out_dir": out,
            "max_genomes": max_genomes,
            "reference_only": reference_only,
            "identity": identity,
            "genome_dir": genome_dir,
            "gff_dir": gff_dir,
            "traits_csv": traits_csv,
            "gpa_csv": gpa_csv,
            "tree": tree,
            "count_table": count_table,
            "pangenome_faa": pangenome_faa,
            "cog_faa": cog_faa,
            "cog_def": cog_def,
        }
        # Pass-through --key value tokens override / extend the explicit set
        candidate.update(_parse_recipe_extra(ctx.args))
        kwargs = {
            k: v for k, v in candidate.items()
            if k in sig.parameters and v is not None
        }
        # Warn about tokens that don't match any recipe parameter
        unknown = [
            k for k in _parse_recipe_extra(ctx.args)
            if k not in sig.parameters
        ]
        if unknown:
            rprint(
                f"[yellow]Ignored unknown option(s) for {name!r}: "
                f"{', '.join('--' + u.replace('_', '-') for u in unknown)}[/]"
            )
        # Validate required parameters that have no default
        missing = [
            n for n, p in sig.parameters.items()
            if p.default is inspect.Parameter.empty and n not in kwargs
        ]
        if missing:
            hint = "  ".join(
                f"--{m.replace('_', '-')} <value>" for m in missing
            )
            rprint(
                f"[red]Recipe {name!r} requires: {', '.join(missing)}.[/]\n"
                f"[dim]Pass each as an option, e.g.:[/] {hint}"
            )
            raise typer.Exit(code=1)

        try:
            result = pipe(**kwargs)
        except Exception as exc:
            rprint(f"[red]Recipe failed:[/] {exc}")
            raise typer.Exit(code=1)

        rprint(f"\n[green]✓ Recipe done.[/]  result.out_dir = {getattr(result, 'out_dir', '?')}")
        return

    rprint(f"[red]Unknown action {action!r}.[/]  Use: list | show | run")
    raise typer.Exit(code=1)


@app.command("llm")
def llm_cmd(
    action: str = typer.Argument(...,
        help="explain | diagnose | redact | new-tool | suggest | audit"),
    term: Optional[str] = typer.Argument(None,
        help="For 'explain': the term.  For others: ignored."),
    context: str = typer.Option(
        "comparative_genomics", "--context", "-c",
        help="Short disambiguation hint (no data, just a category word).",
    ),
    backend: Optional[str] = typer.Option(
        None, "--backend",
        help="Override BIOFLOW_LLM_BACKEND env var "
             "(anthropic | openai | ollama | disabled).",
    ),
    max_tokens: int = typer.Option(350, "--max-tokens",
        help="Cap on response length."),
    # diagnose-specific
    stage: Optional[str] = typer.Option(None, "--stage",
        help="[diagnose] failed stage name."),
    command: Optional[str] = typer.Option(None, "--command",
        help="[diagnose] the failed shell command (will be redacted)."),
    stderr_path: Optional[Path] = typer.Option(None, "--stderr",
        help="[diagnose] path to a file holding the failed command's stderr."),
    exit_code: int = typer.Option(1, "--exit-code",
        help="[diagnose] exit code returned by the failed run."),
    workspace: Optional[Path] = typer.Option(None, "--workspace",
        help="[diagnose] workspace path to redact in the prompt."),
    audit_log: Optional[Path] = typer.Option(None, "--audit",
        help="[diagnose] append redacted prompt + response to this file."),
    # new-tool / suggest specific
    tool_name: Optional[str] = typer.Option(None, "--tool",
        help="[new-tool, suggest] tool name (e.g. prokka)."),
    help_path: Optional[Path] = typer.Option(None, "--help-file",
        help="[new-tool] path to a file holding `<tool> --help` output."),
    image_hint: Optional[str] = typer.Option(None, "--image",
        help="[new-tool] suggested container image tag."),
    intent: Optional[str] = typer.Option(None, "--intent",
        help="[suggest] short text describing what you want the command to do."),
) -> None:
    """LLM companion (opt-in, privacy-first).

    \b
    Phase 1 — terminology Q&A (zero data exposure):
      bioflow llm explain "Bonferroni correction"

    \b
    Phase 2 — error diagnosis (opt-in, all inputs redacted):
      bioflow llm diagnose --stage prokka --exit-code 1 \\
          --command "$(cat last_command.sh)" \\
          --stderr last.stderr.log

    \b
    Helper:
      bioflow llm redact   # paste text on stdin, get redacted text on stdout

    Default backend is ``disabled`` so a fresh install never makes
    network calls without explicit opt-in.
    """
    from bioflow.llm import (  # noqa: PLC0415
        explain, diagnose_failure, redact,
        LlmDisabled, LlmError, CapExceeded,
    )

    if action == "explain":
        if not term:
            rprint("[red]A term to explain is required.[/]")
            raise typer.Exit(code=1)
        try:
            text = explain(term, context=context, max_tokens=max_tokens, backend=backend)
        except LlmDisabled as exc:
            rprint(f"[yellow]LLM disabled:[/] {exc}")
            raise typer.Exit(code=2)
        except CapExceeded as exc:
            rprint(f"[yellow]Cost cap reached:[/] {exc}")
            raise typer.Exit(code=3)
        except LlmError as exc:
            rprint(f"[red]LLM error:[/] {exc}")
            raise typer.Exit(code=1)
        rprint(f"\n[bold cyan]{term}[/]")
        rprint(f"[dim]({context})[/]\n")
        rprint(text)
        return

    if action == "diagnose":
        if not stage or not command:
            rprint("[red]--stage and --command are required for diagnose.[/]")
            raise typer.Exit(code=1)
        stderr_text = ""
        if stderr_path:
            try:
                from bioflow.io import read_text  # noqa: PLC0415
                stderr_text = read_text(stderr_path)
            except OSError as exc:
                rprint(f"[red]Could not read stderr file:[/] {exc}")
                raise typer.Exit(code=1)
        try:
            text = diagnose_failure(
                stage_name=stage,
                command=command,
                stderr=stderr_text,
                exit_code=exit_code,
                workspace=str(workspace) if workspace else None,
                max_tokens=max_tokens,
                backend=backend,
                audit_log=audit_log,
            )
        except LlmDisabled as exc:
            rprint(f"[yellow]LLM disabled:[/] {exc}")
            raise typer.Exit(code=2)
        except LlmError as exc:
            rprint(f"[red]LLM error:[/] {exc}")
            raise typer.Exit(code=1)
        rprint(f"\n[bold]Diagnosis for stage[/] [cyan]{stage}[/] (exit={exit_code}):\n")
        rprint(text)
        rprint("\n[dim](LLM proposes — review before re-running)[/]")
        return

    if action == "redact":
        # Read from stdin, emit redacted output (also a Tier-B safety
        # check: paste a stderr log to see what would have been sent)
        import sys as _sys  # noqa: PLC0415
        raw = _sys.stdin.read()
        rprint(redact(raw, workspace=str(workspace) if workspace else None))
        return

    if action == "new-tool":
        from bioflow.llm import new_tool  # noqa: PLC0415
        if not tool_name:
            rprint("[red]--tool is required.[/]")
            raise typer.Exit(code=1)
        if help_path is None:
            rprint("[red]--help-file <path> is required "
                   "(capture `<tool> --help` into a file first).[/]")
            raise typer.Exit(code=1)
        try:
            from bioflow.io import read_text  # noqa: PLC0415
            help_txt = read_text(help_path)
        except OSError as exc:
            rprint(f"[red]Could not read --help-file: {exc}[/]")
            raise typer.Exit(code=1)
        try:
            yaml = new_tool(
                name=tool_name,
                help_text=help_txt,
                image_hint=image_hint or "",
                max_tokens=max_tokens,
                backend=backend,
            )
        except LlmDisabled as exc:
            rprint(f"[yellow]LLM disabled:[/] {exc}")
            raise typer.Exit(code=2)
        except LlmError as exc:
            rprint(f"[red]LLM error:[/] {exc}")
            raise typer.Exit(code=1)
        rprint(f"\n[bold]Draft tool YAML for[/] [cyan]{tool_name}[/]"
               "  [dim](review before committing)[/]\n")
        print(yaml)
        return

    if action == "audit":
        from bioflow.llm import audit as _audit  # noqa: PLC0415
        entries = _audit.read_entries(limit=20)
        if not entries:
            rprint("[yellow]No LLM calls recorded yet.[/]")
            return
        today = _audit.today_total_usd()
        cap = _audit._load_cap()
        rprint(f"\n[bold]LLM audit log[/]  ({_audit.AUDIT_PATH})\n")
        for e in entries:
            cost = e.get("cost_usd")
            cost_str = f"${cost:.5f}" if isinstance(cost, (int, float)) else "—"
            rprint(
                f"  [dim]{e.get('ts','?'):<25s}[/]  "
                f"{e.get('action','?'):<20s}  "
                f"{e.get('backend','?'):<10s}  "
                f"in={e.get('input_tokens',0):>5d}  "
                f"out={e.get('output_tokens',0):>5d}  "
                f"cost={cost_str}"
            )
        rprint(f"\n[bold]Today (UTC):[/] ${today:.4f}"
               + (f"  [dim]/ cap ${cap:.2f}[/]" if cap is not None else ""))
        return

    if action == "suggest":
        from bioflow.llm import suggest_command  # noqa: PLC0415
        if not tool_name or not intent:
            rprint("[red]--tool and --intent are required.[/]")
            raise typer.Exit(code=1)
        try:
            cmd = suggest_command(
                tool=tool_name, intent=intent,
                backend=backend, max_tokens=max_tokens,
            )
        except LlmDisabled as exc:
            rprint(f"[yellow]LLM disabled:[/] {exc}")
            raise typer.Exit(code=2)
        except LlmError as exc:
            rprint(f"[red]LLM error:[/] {exc}")
            raise typer.Exit(code=1)
        rprint(f"\n[bold]Suggested command for[/] [cyan]{tool_name}[/]"
               "  [dim](review — uses {placeholder} for inputs)[/]\n")
        print(cmd)
        return

    rprint(f"[red]Unknown action {action!r}.[/]  "
           "Use: explain | diagnose | redact | new-tool | suggest | audit")
    raise typer.Exit(code=1)


@app.command("setup")
def setup_cmd(
    backend: Optional[str] = typer.Option(
        None, "--backend",
        help="Skip the interactive prompt and configure this backend "
             "directly (disabled | ollama | anthropic | openai).",
    ),
    model: Optional[str] = typer.Option(None, "--model",
        help="Override the recommended model name."),
    yes: bool = typer.Option(False, "--yes", "-y",
        help="Accept the auto-recommendation without prompting."),
) -> None:
    """First-time setup — picks an LLM backend that fits this machine.

    \b
    What it does:
      1. Detects CPU / RAM / GPU.
      2. Recommends a local Ollama model that fits, or suggests cloud APIs.
      3. Saves the choice to ~/.bioflow/config.yaml so future runs honour it.

    \b
    Examples:
      bioflow setup                          # interactive
      bioflow setup --yes                    # accept recommendation as-is
      bioflow setup --backend disabled       # explicit no-LLM mode
      bioflow setup --backend anthropic      # use cloud Anthropic
    """
    from bioflow.core.hardware import detect  # noqa: PLC0415
    from bioflow.llm import (  # noqa: PLC0415
        recommend_local_model, save_config,
    )

    hw = detect()
    rec = recommend_local_model(
        ram_gb=hw.ram_gb, gpu_present=hw.gpu_present, cpu_count=hw.cpu_count,
    )

    console.print(
        f"\n[bold]Detected hardware[/]\n"
        f"  CPU:        {hw.cpu_count}\n"
        f"  RAM:        {hw.ram_gb:.1f} GB\n"
        f"  GPU:        {'present' if hw.gpu_present else 'none'}\n"
        f"  Disk free:  {hw.disk_free_gb:.1f} GB\n"
        f"  OS / arch:  {hw.os} / {hw.arch}\n"
    )
    console.print(f"[bold]Recommendation[/]: [cyan]{rec.backend}[/]"
                  + (f" ({rec.model})" if rec.model else ""))
    console.print(f"[dim]  {rec.reason}[/]\n")

    # Resolve choice
    if backend is None:
        if yes:
            backend = rec.backend
            model = model or rec.model
        else:
            console.print("Choose backend:")
            console.print("  1) disabled    (no LLM — safest default)")
            console.print(
                f"  2) ollama      (local, recommended model: {rec.model or 'n/a'})"
            )
            console.print("  3) anthropic   (cloud, requires ANTHROPIC_API_KEY env var)")
            console.print("  4) openai      (cloud, requires OPENAI_API_KEY env var)")
            choice = typer.prompt("Selection [1-4]", default="2")
            backend = {
                "1": "disabled", "2": "ollama",
                "3": "anthropic", "4": "openai",
            }.get(choice.strip(), rec.backend)
            if backend == "ollama" and not model:
                model = typer.prompt(
                    "Ollama model", default=rec.model or "qwen2.5-coder:7b",
                )
            elif backend in ("anthropic", "openai") and not model:
                default_model = (
                    "claude-3-5-haiku-latest" if backend == "anthropic"
                    else "gpt-4o-mini"
                )
                model = typer.prompt("Model name", default=default_model)

    backend = (backend or "disabled").lower().strip()
    if backend not in ("disabled", "ollama", "anthropic", "openai"):
        rprint(f"[red]Unknown backend {backend!r}.[/]")
        raise typer.Exit(code=1)

    cfg: dict = {"backend": backend}
    if backend != "disabled" and model:
        cfg["model"] = model
    if backend == "ollama":
        cfg["endpoint"] = "http://localhost:11434"

    # Optional daily cost cap — only relevant for cloud backends
    if backend in ("anthropic", "openai") and not yes:
        cap_str = typer.prompt(
            "Daily cost cap (USD, 0 = no cap)",
            default="5.00",
        )
        try:
            cap_val = float(cap_str)
        except ValueError:
            cap_val = 0.0
        if cap_val > 0:
            cfg["daily_cost_cap_usd"] = cap_val

    path = save_config(cfg)
    rprint(f"\n[green]✓ Saved[/] → [dim]{path}[/]")

    # Helpful next-step hints
    if backend == "ollama":
        rprint(
            "\nNext: install Ollama from [cyan]https://ollama.com[/], then pull the model:"
        )
        rprint(f"  [dim]ollama pull {model}[/]")
        rprint("  [dim]ollama serve[/]   # leaves a local daemon running")
    elif backend == "anthropic":
        rprint("\nNext: export your API key:")
        rprint("  [dim]export ANTHROPIC_API_KEY=sk-ant-...[/]")
    elif backend == "openai":
        rprint("\nNext: export your API key:")
        rprint("  [dim]export OPENAI_API_KEY=sk-...[/]")
    else:
        rprint(
            "\n[dim]LLM is off.  Re-run `bioflow setup` any time to change.[/]"
        )


if __name__ == "__main__":
    app()
