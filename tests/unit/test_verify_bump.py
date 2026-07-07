"""verify_bump maps bumped tools to the right behaviour check.

The Docker smokes themselves need a daemon (exercised in integration/nightly);
here we only lock down the non-Docker wiring: every SMOKE key is a real tool,
and a bumped tool resolves to the recipes whose e2e must run.

See scripts/verify_bump.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_bump.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_bump", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


VB = _load()


def test_smoke_keys_are_real_tools():
    reg = VB._registry()
    unknown = [t for t in VB.SMOKE if t not in reg]
    assert not unknown, f"SMOKE references unknown tool ids: {unknown}"


def test_e2e_covered_tool_triggers_its_recipe_e2e():
    """A bump to a tool used by a covered recipe must resolve to that recipe's
    full-pipeline e2e — the reliable check for the prokka-0-CDS class."""
    reg = VB._registry()
    e2e = VB._recipes_with_e2e()
    assert "prokaryote_assembly" in e2e and "pangenome" in e2e
    prokka_img = (reg["prokka"].get("container") or {}).get("image", "")
    covered = VB._recipes_using(prokka_img) & e2e
    assert {"prokaryote_assembly", "pangenome"} <= covered


def test_uncovered_tool_falls_back_to_smoke():
    """A tool whose recipes have no e2e still gets a container smoke entry (real
    or liveness) or a derived liveness probe — never silently unchecked."""
    reg = VB._registry()
    e2e = VB._recipes_with_e2e()
    # macs3's recipes (chip_seq/atac_seq) have no e2e; it must have a smoke.
    macs3_img = (reg["macs3"].get("container") or {}).get("image", "")
    assert not (VB._recipes_using(macs3_img) & e2e)
    assert "macs3" in VB.SMOKE
    # even a tool with no explicit SMOKE entry gets a non-empty liveness probe
    probe = VB._liveness(reg["macs3"])
    assert probe and probe != "true"
