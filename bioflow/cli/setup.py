"""`bioflow setup` — first-time LLM backend wizard."""
from __future__ import annotations

from typing import Optional

import typer
from rich import print as rprint

from bioflow.cli._app import app, console


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
