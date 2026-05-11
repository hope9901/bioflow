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
from pathlib import Path
from typing import Iterable, Optional

from bioflow.core.logger import get_logger

log = get_logger()

__all__ = [
    "explain",
    "diagnose_failure",
    "redact",
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

def _backend() -> str:
    """Return the configured backend name.  Reads env BIOFLOW_LLM_BACKEND.

    Honours the rule "LLM is opt-in".  Default = ``disabled``.
    Recognised values: ``disabled`` | ``anthropic`` | ``openai`` | ``ollama``.
    """
    return os.environ.get("BIOFLOW_LLM_BACKEND", "disabled").lower().strip()


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
    model = os.environ.get("BIOFLOW_LLM_MODEL", "claude-3-5-haiku-latest")
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
    model = os.environ.get("BIOFLOW_LLM_MODEL", "gpt-4o-mini")
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

    endpoint = os.environ.get(
        "BIOFLOW_LLM_ENDPOINT", "http://localhost:11434"
    ).rstrip("/")
    model = os.environ.get("BIOFLOW_LLM_MODEL", "qwen2.5-coder:7b")
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
