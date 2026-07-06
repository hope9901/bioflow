#!/usr/bin/env python3
"""Fetch per-tool citation counts for the registry from Europe PMC.

For every ``registry/tools/**/*.yaml`` we pull the PMID out of its
``citation:`` field and ask Europe PMC (free, no key) two questions:

  * **total**  — how many papers cite that reference, ever
    (``/MED/<pmid>/citations`` → ``hitCount``)
  * **recent** — how many cite it in the last ``RECENT_YEARS`` *complete*
    calendar years (``search?query=CITES:<pmid>_MED AND FIRST_PDATE:[…]``)

Total says "is this a standard tool"; recent says "is it still in active use".

Network lives here only — the result is cached to ``registry/tool_citations.json``
so ``gen_docs.py`` and CI stay offline/deterministic.  A monthly workflow
re-runs this and commits the refreshed numbers.  Transient failures keep the
previous value (so one flaky fetch never wipes the data).

Honest caveats (surfaced in the docs): citation counts are a *lower bound* on
use (people forget to cite), older tools accrue more, and tools without a
formal PMID show ``n/a``.

Usage::

    python scripts/fetch_tool_citations.py            # refresh all
    python scripts/fetch_tool_citations.py --limit 3  # smoke-test a few
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path


def _norm(s: str) -> str:
    """Lower-case + strip diacritics so 'Röst' matches 'Rost', 'Ramírez'
    matches 'Ramirez', etc. (author surnames carry accents inconsistently)."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)
    ).lower()

RECENT_YEARS = 5
_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_ROOT = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _ROOT / "registry" / "tools"
_OUT = _ROOT / "registry" / "tool_citations.json"
_PMID_RE = re.compile(r"PMID\s*[:#]?\s*(\d{4,9})", re.IGNORECASE)
_USER_AGENT = "bioflow-citation-fetcher (+https://github.com/hope9901/bioflow)"


def _recent_window() -> "tuple[int, int]":
    """Last RECENT_YEARS complete calendar years (ends last year)."""
    end = _dt.date.today().year - 1
    return end - RECENT_YEARS + 1, end


def _get_json(url: str, *, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as fh:
                return json.load(fh)
        except Exception as exc:  # noqa: BLE001 - network is best-effort
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} tries: {url}\n  {last}")


def _hit_count(query: str) -> int:
    q = urllib.parse.urlencode(
        {"query": query, "format": "json", "pageSize": "1", "resultType": "idlist"}
    )
    return int(_get_json(f"{_BASE}/search?{q}").get("hitCount", 0))


def _total_citations(pmid: str) -> int:
    return int(_get_json(
        f"{_BASE}/MED/{pmid}/citations?format=json&pageSize=1"
    ).get("hitCount", 0))


def _verify(pmid: str, surname: str, year: "int | None") -> "tuple[bool, str]":
    """A PMID is trusted only if the paper it points to actually matches the
    citation's author surname + year (±1).  Several registry PMIDs turned out
    to reference unrelated papers; without this guard we'd publish citation
    counts for the *wrong* article.  Returns (verified, referenced_title)."""
    q = urllib.parse.urlencode(
        {"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json",
         "pageSize": "1", "resultType": "lite"}
    )
    res = _get_json(f"{_BASE}/search?{q}").get("resultList", {}).get("result", [])
    if not res:
        return False, ""
    rec = res[0]
    title = rec.get("title", "")
    py = rec.get("pubYear")
    ok = bool(surname) and _norm(surname) in _norm(rec.get("authorString") or "") and (
        year is not None and py is not None and abs(int(py) - year) <= 1
    )
    return ok, title, (rec.get("doi") or None)


def _iter_tools():
    for p in sorted(_TOOLS_DIR.rglob("*.yaml")):
        text = p.read_text(encoding="utf-8")
        tid = re.search(r"^id:\s*(\S+)", text, re.MULTILINE)
        name = re.search(r"^name:\s*(.+)", text, re.MULTILINE)
        cat = re.search(r"^category:\s*(\S+)", text, re.MULTILINE)
        cit = re.search(r"^citation:\s*(.+)", text, re.MULTILINE)
        cit_s = cit.group(1) if cit else ""
        pmid = _PMID_RE.search(cit_s)
        yr = re.search(r"\b(19|20)\d{2}\b", cit_s)
        au = re.match(r'\s*"?\s*([A-Za-z\-]+)', cit_s)
        yield {
            "id": tid.group(1).strip() if tid else p.stem,
            "name": name.group(1).strip().strip("\"'") if name else p.stem,
            "category": cat.group(1).strip() if cat else "",
            "pmid": pmid.group(1) if pmid else None,
            "surname": au.group(1) if au else "",
            "year": int(yr.group(0)) if yr else None,
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N tools")
    ap.add_argument("--sleep", type=float, default=0.34, help="seconds between requests")
    args = ap.parse_args()

    start, end = _recent_window()
    prev: dict = {}
    if _OUT.exists():
        try:
            prev = json.loads(_OUT.read_text(encoding="utf-8")).get("tools", {})
        except Exception:
            prev = {}

    tools = list(_iter_tools())
    if args.limit:
        tools = tools[: args.limit]

    out: dict = {}
    n_pmid = n_ok = n_bad = 0
    for i, t in enumerate(tools, 1):
        tid, pmid = t["id"], t["pmid"]
        rec = {"pmid": pmid, "doi": None, "total": None, "recent": None,
               "verified": None, "name": t["name"], "category": t["category"]}
        if pmid:
            n_pmid += 1
            try:
                ok, title, doi = _verify(pmid, t["surname"], t["year"])
                time.sleep(args.sleep)
                rec["verified"] = ok
                if ok:
                    rec["doi"] = doi
                    rec["total"] = _total_citations(pmid)
                    time.sleep(args.sleep)
                    rec["recent"] = _hit_count(
                        f"CITES:{pmid}_MED AND (FIRST_PDATE:[{start}-01-01 TO {end}-12-31])"
                    )
                    time.sleep(args.sleep)
                    n_ok += 1
                else:
                    # PMID points to a paper that is NOT this tool's reference —
                    # record it so the wrong article is easy to spot and fix.
                    rec["ref_title"] = title[:80]
                    n_bad += 1
            except Exception as exc:  # keep previous numbers on a flaky fetch
                old = prev.get(tid, {})
                rec["total"] = old.get("total")
                rec["recent"] = old.get("recent")
                rec["verified"] = old.get("verified")
                sys.stderr.write(f"  ! {tid} (PMID {pmid}): {exc}\n")
        out[tid] = rec
        flag = "" if rec["verified"] else ("  <-- PMID MISMATCH" if pmid else "")
        print(f"[{i}/{len(tools)}] {tid:22} PMID={pmid or '-':>9} "
              f"total={rec['total']} recent={rec['recent']}{flag}")

    payload = {
        "source": "Europe PMC",
        "metric": "citations of each tool's canonical reference (PMID), "
                  "shown only when the PMID's author+year match the citation",
        "recent_window": {"start": start, "end": end, "years": RECENT_YEARS},
        "fetched_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "n_tools": len(tools),
        "n_with_pmid": n_pmid,
        "n_fetched": n_ok,
        "n_pmid_mismatch": n_bad,
        "tools": dict(sorted(out.items())),
    }
    _OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {_OUT.relative_to(_ROOT)} - "
          f"{n_ok}/{n_pmid} PMIDs fetched, window {start}-{end}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
