"""LLM L6 — audit log + daily cost cap.

Every LLM call lands here.  One JSON object per line in
``~/.bioflow/llm_audit.log``:

  {"ts": "...", "action": "explain", "backend": "anthropic",
   "model": "claude-3-5-haiku-latest", "input_tokens": 73,
   "output_tokens": 142, "cost_usd": 0.00079,
   "redacted_prompt": "Term: Bonferroni correction\\nContext: ..."}

Cost tracking
-------------
A small per-backend × per-model table maps token counts to USD.  Local
Ollama is hard-coded to $0.  Today's running total is the sum of
``cost_usd`` over every log entry whose ``ts`` falls within the current
UTC day.

Cap enforcement
---------------
``daily_cost_cap_usd`` lives under ``llm:`` in
``~/.bioflow/config.yaml``.  When set, an LLM call that would push the
day's total above the cap is refused with :class:`LlmError`; the user
sees a clear message including the current spend and the cap.

Design
------
* The audit log path is a module-level attribute so tests can rebind it.
* All pricing entries are explicit — when a model isn't in the table,
  cost is recorded as ``None`` (which counts as 0 for cap purposes but
  is preserved in the log so admins can spot it).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Optional

from bioflow.core.logger import get_logger

log = get_logger()


AUDIT_PATH = Path.home() / ".bioflow" / "llm_audit.log"
"""Default audit log path.  Tests rebind this attribute."""


# ---------------------------------------------------------------------------
# Pricing — USD per 1 million input / output tokens, as of 2026-04
# ---------------------------------------------------------------------------

_PRICING: dict = {
    # Anthropic
    "claude-3-5-haiku-latest":   (1.00,   5.00),
    "claude-3-5-haiku-20241022": (1.00,   5.00),
    "claude-3-5-sonnet-latest":  (3.00,  15.00),
    "claude-3-5-sonnet-20241022":(3.00,  15.00),
    "claude-3-opus-20240229":   (15.00,  75.00),
    # OpenAI
    "gpt-4o-mini":               (0.15,   0.60),
    "gpt-4o":                    (2.50,  10.00),
    "gpt-4-turbo":              (10.00,  30.00),
    # Local (free)
    "_ollama":                   (0.00,   0.00),
}


def estimate_cost(
    backend: str, model: str,
    input_tokens: int, output_tokens: int,
) -> Optional[float]:
    """Convert token counts into USD using the static :data:`_PRICING` table.

    Returns ``None`` when the (backend, model) pair isn't priced — caller
    treats this as 0 for cap purposes but the audit log records ``None``
    so an admin can notice an unpriced model.
    """
    if backend == "ollama":
        return 0.0
    if backend == "disabled":
        return 0.0
    rates = _PRICING.get(model)
    if rates is None:
        return None
    in_rate, out_rate = rates
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


# ---------------------------------------------------------------------------
# Append / read
# ---------------------------------------------------------------------------

def record(
    *,
    action: str,
    backend: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: Optional[float] = None,
    redacted_prompt: str = "",
    extra: Optional[dict] = None,
) -> None:
    """Append one entry to the audit log.

    Never raises on log-write failure (we don't want a logging glitch to
    block the user's actual analysis), just emits a warning.
    """
    entry = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "action": action,
        "backend": backend,
        "model": model,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cost_usd": cost_usd,
    }
    if redacted_prompt:
        # Trim very long prompts to keep the log readable; the *full*
        # prompt was just sent and is recoverable from the model
        # provider's audit if needed.
        entry["redacted_prompt"] = (
            redacted_prompt[:500] + "…<trunc>"
            if len(redacted_prompt) > 500 else redacted_prompt
        )
    if extra:
        entry["extra"] = extra

    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Append JSONL.  newline="" keeps explicit \n control across OS.
        with AUDIT_PATH.open("a", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning(f"Could not append audit log: {exc}")


def read_entries(limit: Optional[int] = None) -> list:
    """Return the audit log as a list of dicts (oldest first)."""
    if not AUDIT_PATH.exists():
        return []
    out: list = []
    with AUDIT_PATH.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None and len(out) > limit:
        return out[-limit:]
    return out


# ---------------------------------------------------------------------------
# Today's spend + cap enforcement
# ---------------------------------------------------------------------------

def today_total_usd() -> float:
    """Sum ``cost_usd`` across audit entries whose ``ts`` falls today (UTC)."""
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    total = 0.0
    for entry in read_entries():
        ts = entry.get("ts", "")
        cost = entry.get("cost_usd")
        if cost is None:
            continue
        if ts.startswith(today):
            try:
                total += float(cost)
            except (TypeError, ValueError):
                pass
    return total


def _load_cap() -> Optional[float]:
    """Read ``llm.daily_cost_cap_usd`` from the config file, or env var."""
    # Env var wins
    env = os.environ.get("BIOFLOW_LLM_DAILY_CAP_USD")
    if env:
        try:
            return float(env)
        except ValueError:
            log.warning(f"Bad BIOFLOW_LLM_DAILY_CAP_USD={env!r}; ignoring")
    # Then config file
    try:
        from bioflow.llm import load_config   # noqa: PLC0415
        v = load_config().get("daily_cost_cap_usd")
        if v is not None:
            return float(v)
    except Exception:
        pass
    return None


class CapExceeded(RuntimeError):
    """Raised when an LLM call would push today's spend above the cap."""


def check_cap(estimated_cost: float) -> None:
    """Raise :class:`CapExceeded` when *estimated_cost* + today's spend
    would exceed the configured daily cap.

    No-op when no cap is set, or when the call is free (Ollama / disabled).
    """
    if estimated_cost <= 0:
        return
    cap = _load_cap()
    if cap is None:
        return
    spent = today_total_usd()
    if spent + estimated_cost > cap:
        raise CapExceeded(
            f"Daily LLM cost cap exceeded: "
            f"already spent ${spent:.4f} of ${cap:.2f}, "
            f"this call would add ~${estimated_cost:.4f}.  "
            f"Raise the cap via `bioflow setup` or set "
            f"BIOFLOW_LLM_DAILY_CAP_USD env var."
        )


# ---------------------------------------------------------------------------
# Rough pre-call token estimate (input only — cheap len/4 heuristic)
# ---------------------------------------------------------------------------

def estimate_input_tokens(text: str) -> int:
    """Cheap upper-bound token estimate from character count.

    ~4 chars per English token is the common rule of thumb; this is only
    used for the pre-call cap check, the actual count from the model
    provider replaces it in the audit record.
    """
    return max(1, len(text) // 4)
