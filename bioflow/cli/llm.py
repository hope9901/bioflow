"""`bioflow llm` — opt-in LLM companion (explain / diagnose / new-tool / suggest / audit)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app


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


