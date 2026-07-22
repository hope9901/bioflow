"""A bad ``--set`` swap value must fail fast, not silently run the default.

Recipes branch on a swap param (``if caller == "deepvariant" ... else ...``)
where the ``else`` is the default, so a typo like ``--set caller=deepvarient``
used to fall through to the default with no error.  Every swap recipe now calls
``choice()`` first, so an unknown value raises ``ValueError`` before any I/O.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from bioflow.recipes import choice, get, names

_SWAP_PARAMS = {"annotator", "assembler", "quantifier", "caller",
                "aligner", "profiler", "binner", "counter", "search"}


def _swap_params(pipe):
    """Swap params of a recipe: str-default kwargs its body branches on."""
    src = Path(inspect.getsourcefile(pipe.func)).read_text(encoding="utf-8")
    sig = inspect.signature(pipe.func)
    found = []
    for name, p in sig.parameters.items():
        if name not in _SWAP_PARAMS or not isinstance(p.default, str):
            continue
        if re.search(rf'\b{name}\s*(?:==|!=)\s*"', src):
            found.append(name)
    return found, sig


def test_choice_accepts_valid_and_rejects_invalid():
    assert choice("x", "a", "a", "b") == "a"
    with pytest.raises(ValueError, match="not a valid choice"):
        choice("caller", "typo", "gatk4", "deepvariant")


@pytest.mark.parametrize("recipe_name", names())
def test_invalid_swap_value_raises_before_io(recipe_name, tmp_path):
    pipe = get(recipe_name)
    params, sig = _swap_params(pipe)
    if not params:
        pytest.skip(f"{recipe_name} has no swap point")
    for swap in params:
        kwargs = {}
        for name, p in sig.parameters.items():
            if name == swap:
                kwargs[name] = "__definitely_not_a_tool__"
            elif name == "out_dir":
                kwargs[name] = tmp_path / "out"
            elif p.default is inspect.Parameter.empty:
                kwargs[name] = "x"  # dummy required arg; never reached
        with pytest.raises(ValueError, match="not a valid choice"):
            pipe(**kwargs)
