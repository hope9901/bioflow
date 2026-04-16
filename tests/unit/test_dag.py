"""DAG topological sort tests."""

from __future__ import annotations

import pytest

from bioflow.core.dag import Artifact, StageNode, topological_order


def _node(stage_id: str, tool_id: str, inputs: list[str], outputs: list[str]) -> StageNode:
    return StageNode(
        stage_id=stage_id,
        tool_id=tool_id,
        inputs=[Artifact(name=n, path=f"/w/{n}", kind="dir") for n in inputs],
        outputs=[Artifact(name=n, path=f"/w/{n}", kind="dir") for n in outputs],
    )


def test_linear_chain_preserves_order():
    nodes = [
        _node("s1", "fastp",   inputs=[],            outputs=["clean"]),
        _node("s2", "spades",  inputs=["clean"],     outputs=["assembly"]),
        _node("s3", "quast",   inputs=["assembly"],  outputs=["qc_report"]),
    ]
    order = topological_order(nodes)
    assert [n.stage_id for n in order] == ["s1", "s2", "s3"]


def test_out_of_order_input_is_sorted_correctly():
    nodes = [
        _node("s3", "quast",   inputs=["assembly"],  outputs=["qc_report"]),
        _node("s1", "fastp",   inputs=[],            outputs=["clean"]),
        _node("s2", "spades",  inputs=["clean"],     outputs=["assembly"]),
    ]
    order = topological_order(nodes)
    assert [n.stage_id for n in order] == ["s1", "s2", "s3"]


def test_independent_branches_stable():
    # s1 -> s2, s1 -> s3 (no ordering between s2 and s3; declared order wins)
    nodes = [
        _node("s1", "fastp",  inputs=[],        outputs=["clean"]),
        _node("s2", "spades", inputs=["clean"], outputs=["assembly"]),
        _node("s3", "fastqc", inputs=["clean"], outputs=["qc_html"]),
    ]
    order = topological_order(nodes)
    assert [n.stage_id for n in order] == ["s1", "s2", "s3"]


def test_cycle_raises():
    nodes = [
        _node("a", "x", inputs=["y_out"], outputs=["a_out"]),
        _node("b", "x", inputs=["a_out"], outputs=["y_out"]),
    ]
    with pytest.raises(ValueError, match="Cycle"):
        topological_order(nodes)
