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
from typing import Optional

from bioflow.core.logger import get_logger

log = get_logger()

__all__ = ["explain", "LlmError", "LlmDisabled"]


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
