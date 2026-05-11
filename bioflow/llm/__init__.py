"""bioflow.llm — opt-in language-model companion (privacy-first).

Design tenets (frozen)
----------------------
1. SDK / runtime path NEVER depends on the LLM working.
2. The LLM only PROPOSES — it never auto-executes anything.
3. Sensitive data (FASTA, matrices, sample metadata) is NEVER sent.
4. Backends are pluggable; ``ollama`` keeps everything on localhost.

LLM Phase 1 — terminology Q&A
-----------------------------
The first capability shipped is the lowest-risk one: pure dictionary
lookup with zero data exposure.  Inputs are short user-typed terms,
outputs are short explanations.  No paths, no file content, no genome
data ever touch the wire.

Usage::

    $ bioflow llm explain "Bonferroni correction"
    $ bioflow llm explain "core gene alignment" --context comparative_genomics
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from bioflow.core.logger import get_logger

log = get_logger()

__all__ = [
    "explain",
    "diagnose_failure",
    "suggest_command",
    "new_tool",
    "redact",
    "recommend_local_model",
    "load_config",
    "save_config",
    "LlmError",
    "LlmDisabled",
]


class LlmError(RuntimeError):
    """Raised on LLM-side problems (network, malformed reply, etc.)."""


class LlmDisabled(LlmError):
    """Raised when LLM is configured as ``disabled`` (default off-switch)."""


# ---------------------------------------------------------------------------
# Backend dispatch
# ---------------------------------------------------------------------------

CONFIG_PATH = Path.home() / ".bioflow" / "config.yaml"
"""Default user-level LLM config file.  Created by `bioflow setup`."""


def load_config() -> dict:
    """Load ``~/.bioflow/config.yaml`` if present; otherwise return ``{}``.

    Resolution order for every config knob:
      1. explicit function argument
      2. environment variable (e.g. ``BIOFLOW_LLM_BACKEND``)
      3. config file (this function)
      4. hard-coded default (``disabled``)
    """
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml as _y   # noqa: PLC0415
        data = _y.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return data.get("llm", {}) if isinstance(data, dict) else {}
    except Exception as exc:   # parse / permission error
        log.warning(f"Could not read {CONFIG_PATH}: {exc}")
        return {}


def save_config(cfg: dict) -> Path:
    """Write LLM settings to ``~/.bioflow/config.yaml``.  Creates parents."""
    import yaml as _y   # noqa: PLC0415
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Merge with whatever else is in the file (don't blow away unrelated keys)
    existing: dict = {}
    if CONFIG_PATH.exists():
        try:
            existing = _y.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing["llm"] = cfg
    CONFIG_PATH.write_text(
        _y.safe_dump(existing, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return CONFIG_PATH


def _config_value(key: str, default=None):
    """Look up one key from the config file, with no env-var fallback."""
    return load_config().get(key, default)


def _backend() -> str:
    """Return the configured backend name.  Resolution order:
    env var ``BIOFLOW_LLM_BACKEND`` → config file → ``"disabled"``."""
    env = os.environ.get("BIOFLOW_LLM_BACKEND")
    if env:
        return env.lower().strip()
    cfg = _config_value("backend")
    if cfg:
        return str(cfg).lower().strip()
    return "disabled"


def _model_for_backend(backend: str) -> str:
    """Per-backend model name with env > config > sensible default."""
    env = os.environ.get("BIOFLOW_LLM_MODEL")
    if env:
        return env
    cfg = _config_value("model")
    if cfg:
        return str(cfg)
    return {
        "anthropic": "claude-3-5-haiku-latest",
        "openai":    "gpt-4o-mini",
        "ollama":    "qwen2.5-coder:7b",
    }.get(backend, "")


# ---------------------------------------------------------------------------
# Hardware-based local-model recommendation
# ---------------------------------------------------------------------------

@dataclass
class ModelRec:
    backend: str
    model: str
    reason: str
    ollama_pull_cmd: Optional[str] = None


def recommend_local_model(
    *,
    ram_gb: Optional[float] = None,
    gpu_present: Optional[bool] = None,
    cpu_count: Optional[int] = None,
) -> ModelRec:
    """Pick a sensible LLM backend + model for the host.

    Order of preference, top to bottom:
      * ≥48 GB RAM      → ollama qwen2.5-coder:14b
      * ≥24 GB RAM      → ollama qwen2.5-coder:7b
      * 12-24 GB RAM    → ollama qwen2.5-coder:3b OR llama3.2:3b
      *  6-12 GB RAM    → ollama llama3.2:1b   (functional Q&A only)
      *  <6 GB RAM      → backend=disabled; recommend cloud API instead

    Returns a :class:`ModelRec` with a human-readable reason.  Hardware
    args default to a live :func:`bioflow.core.hardware.detect()` call.
    """
    if ram_gb is None or gpu_present is None or cpu_count is None:
        try:
            from bioflow.core.hardware import detect   # noqa: PLC0415
            hw = detect()
            if ram_gb is None:        ram_gb = hw.ram_gb
            if gpu_present is None:   gpu_present = hw.gpu_present
            if cpu_count is None:     cpu_count = hw.cpu_count
        except Exception:
            ram_gb = ram_gb or 0
            gpu_present = bool(gpu_present)
            cpu_count = cpu_count or 1

    gpu_bonus = 0 if not gpu_present else 8   # treat GPU as +8 GB headroom
    effective = float(ram_gb or 0) + gpu_bonus

    if effective >= 48:
        m = "qwen2.5-coder:14b"
        return ModelRec(
            backend="ollama", model=m,
            reason=f"{ram_gb:.0f} GB RAM"
                   + (" + GPU" if gpu_present else "")
                   + " → 14B local model fits comfortably.",
            ollama_pull_cmd=f"ollama pull {m}",
        )
    if effective >= 24:
        m = "qwen2.5-coder:7b"
        return ModelRec(
            backend="ollama", model=m,
            reason=f"{ram_gb:.0f} GB RAM"
                   + (" + GPU" if gpu_present else "")
                   + " → 7B local model is the sweet spot.",
            ollama_pull_cmd=f"ollama pull {m}",
        )
    if effective >= 12:
        m = "qwen2.5-coder:3b"
        return ModelRec(
            backend="ollama", model=m,
            reason=f"{ram_gb:.0f} GB RAM → 3B local model "
                   "(good for terminology Q&A; diagnosis quality may vary).",
            ollama_pull_cmd=f"ollama pull {m}",
        )
    if effective >= 6:
        m = "llama3.2:1b"
        return ModelRec(
            backend="ollama", model=m,
            reason=f"{ram_gb:.0f} GB RAM is tight; a 1B model can answer "
                   "definitions but won't be helpful for error diagnosis.",
            ollama_pull_cmd=f"ollama pull {m}",
        )
    return ModelRec(
        backend="disabled", model="",
        reason=f"{ram_gb:.0f} GB RAM is below the comfortable local-LLM "
               "threshold.  Recommended: keep LLM disabled, or sign up for "
               "Anthropic / OpenAI API keys and set "
               "BIOFLOW_LLM_BACKEND=anthropic|openai.",
        ollama_pull_cmd=None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain(
    term: str,
    *,
    context: str = "comparative_genomics",
    max_tokens: int = 350,
    backend: Optional[str] = None,
) -> str:
    """Return a short plain-language explanation of *term*.

    Data exposure: only *term* and *context* (a single category word)
    leave the host.  No file paths, no analysis data, no sample names.
    Suitable for default-on terminology lookup.

    Parameters
    ----------
    term :
        The biology / stats / bioinformatics word to define.
    context :
        Short hint to disambiguate (e.g. ``"phylogenetics"``,
        ``"comparative_genomics"``, ``"statistics"``).
    max_tokens :
        Cap on response length.
    backend :
        Override the configured backend.  ``None`` reads
        ``BIOFLOW_LLM_BACKEND`` env var (default ``disabled``).

    Raises
    ------
    LlmDisabled :
        If no backend is configured.
    LlmError :
        Network / API issue.
    """
    if not term or not term.strip():
        raise LlmError("term is empty")
    term = term.strip()

    chosen = (backend or _backend()).lower().strip()
    log.info(f"llm.explain: backend={chosen}  term={term!r}  context={context!r}")

    if chosen in ("disabled", "off", ""):
        raise LlmDisabled(
            "LLM is disabled (default).  Enable by setting "
            "BIOFLOW_LLM_BACKEND=anthropic | openai | ollama."
        )

    prompt = _build_prompt(term, context)
    if chosen == "anthropic":
        return _call_anthropic(prompt, max_tokens=max_tokens)
    if chosen == "openai":
        return _call_openai(prompt, max_tokens=max_tokens)
    if chosen == "ollama":
        return _call_ollama(prompt, max_tokens=max_tokens)
    raise LlmError(
        f"Unknown LLM backend {chosen!r}.  Expected: anthropic | "
        "openai | ollama | disabled."
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a concise bioinformatics tutor.  Given a single term, "
    "produce a 2-4 sentence plain-language explanation followed by "
    "one line of practical context (e.g. when the term appears, what "
    "tools use it).  Do not invent acronyms.  Avoid disclaimers.  "
    "Output plain text — no markdown headings."
)


def _build_prompt(term: str, context: str) -> dict:
    """Returns a dict suitable for any backend that consumes it."""
    user = (
        f"Term: {term}\n"
        f"Context: {context} (this is a short hint, not data)\n\n"
        "Explain in 2-4 sentences."
    )
    return {"system": _SYSTEM_PROMPT, "user": user}


# ---------------------------------------------------------------------------
# Redaction — for L2 (error diagnosis)
# ---------------------------------------------------------------------------

import re as _re

_DEFAULT_REDACT_PATTERNS: tuple = (
    # Windows user paths: C:\Users\someone\... → C:\Users\<USER>\...
    (_re.compile(r"([A-Z]:\\Users\\)[^\\\s]+", _re.IGNORECASE), r"\1<USER>"),
    # Unix user paths: /Users/foo/... or /home/foo/...
    (_re.compile(r"(/Users/|/home/)[^/\s]+"), r"\1<USER>"),
    # Email addresses
    (_re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    ), "<EMAIL>"),
    # IPv4 addresses
    (_re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ), "<IP>"),
    # API keys / long tokens (hex or base64-ish, 24+ chars)
    (_re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), "<TOKEN>"),
)


def redact(
    text: str,
    *,
    workspace: Optional[str] = None,
    extra_patterns: Optional[Iterable[tuple]] = None,
) -> str:
    """Redact paths, emails, IPs, and long tokens from *text*.

    Sanitiser used before any LLM error-diagnosis call.  Always call
    this; never feed raw stderr to a remote model.

    Parameters
    ----------
    text :
        The string to sanitise.
    workspace :
        Absolute path of the bioflow workspace.  Replaced with
        ``<WORKSPACE>`` before per-pattern rules.
    extra_patterns :
        Iterable of ``(compiled_regex, replacement)`` pairs applied in
        addition to the defaults.  For project-specific tokens, e.g.
        ``patient_\\d+``.
    """
    if not text:
        return ""
    out = text
    if workspace:
        out = out.replace(str(workspace), "<WORKSPACE>")
    for pat, repl in _DEFAULT_REDACT_PATTERNS:
        out = pat.sub(repl, out)
    for pat, repl in (extra_patterns or ()):
        out = pat.sub(repl, out)
    return out


# ---------------------------------------------------------------------------
# L2 — Error diagnosis
# ---------------------------------------------------------------------------

_DIAGNOSE_SYSTEM_PROMPT = (
    "You are a bioinformatics CLI debugging assistant.  The user gives "
    "you a redacted shell command and the redacted last lines of its "
    "stderr.  Diagnose the most likely cause in ONE short paragraph, "
    "then propose a fixed command if one is obvious.  Keep responses "
    "under 8 lines.  Never ask for more data; work with what you have. "
    "Never claim certainty when the failure is ambiguous."
)


def diagnose_failure(
    *,
    stage_name: str,
    command: str,
    stderr: str,
    exit_code: int,
    workspace: Optional[str] = None,
    extra_patterns: Optional[Iterable[tuple]] = None,
    max_tokens: int = 400,
    backend: Optional[str] = None,
    audit_log: Optional["Path"] = None,
) -> str:
    """Ask the configured LLM to diagnose a failed stage.

    All inputs are redacted first.  The LLM never auto-runs the
    suggestion; the caller / CLI is responsible for prompting the user
    before re-execution.  When *audit_log* is set, the redacted prompt
    and response are appended for sanity checks.

    Raises :class:`LlmDisabled` if no backend is configured (default).
    """
    chosen = (backend or _backend()).lower().strip()
    if chosen in ("disabled", "off", ""):
        raise LlmDisabled(
            "LLM is disabled.  Enable with BIOFLOW_LLM_BACKEND=…"
        )

    # Sanitise inputs BEFORE building the prompt
    safe_cmd = redact(command, workspace=workspace, extra_patterns=extra_patterns)
    safe_err = redact(stderr or "", workspace=workspace, extra_patterns=extra_patterns)
    # Truncate stderr to the last 2 KB — the bottom is usually where
    # the real failure lives, and shorter prompts cost less.
    if len(safe_err) > 2000:
        safe_err = "…<truncated>…\n" + safe_err[-2000:]

    user = (
        f"Stage: {stage_name}\n"
        f"Exit code: {exit_code}\n"
        f"Command (redacted):\n{safe_cmd}\n\n"
        f"Last stderr (redacted):\n{safe_err}\n\n"
        "Diagnose."
    )
    prompt = {"system": _DIAGNOSE_SYSTEM_PROMPT, "user": user}
    log.info(
        f"llm.diagnose_failure: backend={chosen}  stage={stage_name}  "
        f"command_chars={len(safe_cmd)}  stderr_chars={len(safe_err)}"
    )

    if chosen == "anthropic":
        text = _call_anthropic(prompt, max_tokens=max_tokens)
    elif chosen == "openai":
        text = _call_openai(prompt, max_tokens=max_tokens)
    elif chosen == "ollama":
        text = _call_ollama(prompt, max_tokens=max_tokens)
    else:
        raise LlmError(f"Unknown LLM backend {chosen!r}")

    if audit_log is not None:
        from pathlib import Path as _P
        from bioflow.io import write_text as _wt, read_text as _rt
        ap = _P(audit_log)
        old = _rt(ap) if ap.exists() else ""
        _wt(ap, old + (
            f"\n=== {stage_name} | exit={exit_code} | backend={chosen} ===\n"
            f"--- redacted prompt ---\n{user}\n"
            f"--- response ---\n{text}\n"
        ))
    return text


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: dict, *, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LlmError(
            "ANTHROPIC_API_KEY env var not set; cannot use anthropic backend."
        )
    try:
        import anthropic   # type: ignore[import-not-found]
    except ImportError as exc:
        raise LlmError(
            "Install the `anthropic` package: pip install anthropic"
        ) from exc
    client = anthropic.Anthropic(api_key=api_key)
    model = _model_for_backend("anthropic")
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=prompt["system"],
            messages=[{"role": "user", "content": prompt["user"]}],
        )
    except Exception as exc:
        raise LlmError(f"anthropic call failed: {exc}") from exc
    return msg.content[0].text.strip()


def _call_openai(prompt: dict, *, max_tokens: int) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LlmError(
            "OPENAI_API_KEY env var not set; cannot use openai backend."
        )
    try:
        from openai import OpenAI   # type: ignore[import-not-found]
    except ImportError as exc:
        raise LlmError(
            "Install the `openai` package: pip install openai"
        ) from exc
    client = OpenAI(api_key=api_key)
    model = _model_for_backend("openai")
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
            ],
        )
    except Exception as exc:
        raise LlmError(f"openai call failed: {exc}") from exc
    return resp.choices[0].message.content.strip()


def _call_ollama(prompt: dict, *, max_tokens: int) -> str:
    """Local Ollama backend (no data leaves the host)."""
    import json as _json
    import urllib.error
    import urllib.request

    endpoint = (
        os.environ.get("BIOFLOW_LLM_ENDPOINT")
        or _config_value("endpoint", "http://localhost:11434")
    ).rstrip("/")
    model = _model_for_backend("ollama")
    body = _json.dumps({
        "model": model,
        "system": prompt["system"],
        "prompt": prompt["user"],
        "stream": False,
        "options": {"num_predict": max_tokens},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{endpoint}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LlmError(
            f"ollama backend at {endpoint} unreachable: {exc.reason}.  "
            "Is `ollama serve` running?"
        ) from exc
    except Exception as exc:
        raise LlmError(f"ollama call failed: {exc}") from exc
    return data.get("response", "").strip() or "(empty response)"


# ---------------------------------------------------------------------------
# Generic prompt → backend dispatcher
# ---------------------------------------------------------------------------

def _dispatch(prompt: dict, *, backend: Optional[str], max_tokens: int) -> str:
    chosen = (backend or _backend()).lower().strip()
    if chosen in ("disabled", "off", ""):
        raise LlmDisabled(
            "LLM is disabled.  Enable with BIOFLOW_LLM_BACKEND=… or "
            "run `bioflow setup` to configure once."
        )
    if chosen == "anthropic":
        return _call_anthropic(prompt, max_tokens=max_tokens)
    if chosen == "openai":
        return _call_openai(prompt, max_tokens=max_tokens)
    if chosen == "ollama":
        return _call_ollama(prompt, max_tokens=max_tokens)
    raise LlmError(f"Unknown LLM backend {chosen!r}")


# ---------------------------------------------------------------------------
# L3 — Tool registration assistant
# ---------------------------------------------------------------------------

_NEW_TOOL_SYSTEM_PROMPT = (
    "You convert a bioinformatics tool's --help output into a bioflow "
    "tool YAML draft.  Produce ONLY the YAML, no prose, no fences.  "
    "Required keys: id (lowercase, underscores), name, version, "
    "category (one of: qc, assembly, assembly_qc, repeat, struct_annot, "
    "func_annot, rnaseq_align, deg, enrichment, alignment, metagenomics, "
    "single_cell, epigenomics, proteomics, comparative_genomics), "
    "stage (list), input_types, output_types, applicable {species, "
    "read_type, mode}, container {image, pull_policy}, resources "
    "{min: {cpu, ram_gb, disk_gb}, recommended: {cpu, ram_gb, disk_gb}, "
    "gpu, arch}, command_template, citation, added, last_reviewed.  "
    "Use ISO date for `added` / `last_reviewed`.  Leave a TODO comment "
    "next to anything you guessed."
)


def new_tool(
    *,
    name: str,
    help_text: str,
    image_hint: str = "",
    max_tokens: int = 800,
    backend: Optional[str] = None,
) -> str:
    """Ask the LLM to draft a tool YAML from *name* + its --help output.

    Privacy note: tool ``--help`` text is the binary's public documentation
    — nothing user-specific is sent.  Suitable as an opt-in default.

    The caller (typically the CLI) should write the returned YAML to a
    file and have the user *review* before committing it to the registry.
    bioflow never auto-registers an LLM-generated tool.
    """
    if not name.strip():
        raise LlmError("tool name is empty")
    if not help_text.strip():
        raise LlmError("help_text is empty (capture `<tool> --help` output)")

    user = (
        f"Tool name: {name}\n"
        f"Suggested container image: {image_hint or '(unknown — guess from name + version)'}\n\n"
        f"--help output:\n```\n{help_text[:6000]}\n```\n\n"
        "Draft the bioflow tool YAML."
    )
    log.info(f"llm.new_tool: name={name!r}  help_chars={len(help_text)}")
    return _dispatch(
        {"system": _NEW_TOOL_SYSTEM_PROMPT, "user": user},
        backend=backend, max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# L4 — Command suggestion
# ---------------------------------------------------------------------------

_SUGGEST_CMD_SYSTEM_PROMPT = (
    "You are a bioinformatics CLI assistant.  Given a tool name and a "
    "short user intent, suggest a single working shell command line.  "
    "Output ONLY the command — no prose, no fences, no leading $.  "
    "Use {out_dir}, {r1}, {r2}, {assembly_fasta}, etc. as placeholders "
    "wherever an input path would go.  Keep flags conservative and "
    "documented."
)


def suggest_command(
    *,
    tool: str,
    intent: str,
    backend: Optional[str] = None,
    max_tokens: int = 250,
) -> str:
    """Suggest a shell command for *tool* that matches *intent*.

    Privacy note: tool name + intent string are the only user-controlled
    bytes sent.  Do NOT include file paths or sample identifiers in
    *intent* — keep it generic (e.g. "annotate paired-end E. coli
    assembly", not "annotate /data/run_42/sample.fna").

    The returned command is a *suggestion*.  The caller pastes it into
    a ``@stage`` function body after review.
    """
    if not tool.strip() or not intent.strip():
        raise LlmError("tool and intent are required")

    user = (
        f"Tool: {tool}\n"
        f"Intent: {intent}\n\n"
        "Propose one shell command using {placeholder} syntax for inputs."
    )
    log.info(
        f"llm.suggest_command: tool={tool!r}  intent_chars={len(intent)}"
    )
    return _dispatch(
        {"system": _SUGGEST_CMD_SYSTEM_PROMPT, "user": user},
        backend=backend, max_tokens=max_tokens,
    )
