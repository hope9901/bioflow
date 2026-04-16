"""Stage dependency DAG (file-artifact based).

Each stage declares the artifacts it consumes (inputs) and produces (outputs).
`topological_order()` sorts stages so that every input is produced by an earlier
stage — it also detects cycles and stable-preserves the declared order when
several stages are free to run at the same time.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    name: str        # canonical name, e.g. "reads_qc_trimmed_r1"
    path: str        # path inside the shared /workspace volume
    kind: str        # fastq | bam | vcf | fasta | gff | tsv | dir | ...


class StageNode(BaseModel):
    stage_id: str
    tool_id: str
    inputs: list[Artifact] = Field(default_factory=list)
    outputs: list[Artifact] = Field(default_factory=list)


def topological_order(nodes: list[StageNode]) -> list[StageNode]:
    """Stable topological sort on artifact dependencies.

    Raises ValueError if a cycle exists.
    """
    # Map artifact name -> producing stage_id
    producer: dict[str, str] = {}
    for n in nodes:
        for a in n.outputs:
            producer[a.name] = n.stage_id

    # Build dependencies: deps[stage_id] = set(upstream stage_ids)
    deps: dict[str, set[str]] = {n.stage_id: set() for n in nodes}
    for n in nodes:
        for a in n.inputs:
            up = producer.get(a.name)
            if up and up != n.stage_id:
                deps[n.stage_id].add(up)

    order: list[StageNode] = []
    remaining = list(nodes)  # preserves declared order for ties
    while remaining:
        progressed = False
        for i, n in enumerate(remaining):
            if not deps[n.stage_id]:
                order.append(n)
                remaining.pop(i)
                for s in deps.values():
                    s.discard(n.stage_id)
                progressed = True
                break
        if not progressed:
            ids = [n.stage_id for n in remaining]
            raise ValueError(f"Cycle or missing dependency in DAG; remaining: {ids}")
    return order
