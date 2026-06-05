"""Pipeline class + @pipeline decorator — multi-stage composition.

Pipelines are intentionally *plain Python*: the decorated body composes
stages with normal control flow, and the SDK only adds inspection
(``show_graph`` / ``dry_run``) and a stable name for CLI dispatch.
"""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from bioflow.core.logger import get_logger

from bioflow.sdk._stage import Stage

log = get_logger()


@dataclass
class Pipeline:
    """A user-defined function that composes one or more :class:`Stage`
    calls into a runnable analysis.

    Use :func:`pipeline` as a decorator rather than instantiating directly.

    Pipelines are deliberately *plain Python* — bioflow does not parse,
    transform, or schedule the body.  The body just calls stages, threads
    results through, and returns whatever the last stage emitted.

    What :class:`Pipeline` adds on top of a bare function:

    * a stable ``name`` and ``description`` for CLI / report use
    * an explicit ``stages`` list so ``show_graph()`` and ``dry_run()``
      can render a DAG without executing anything
    * a single entry point (``run`` / ``__call__``) that other tooling
      can dispatch to (e.g. a future ``bioflow recipe run <name>``)

    The chaining itself remains user-visible inside the body — stages are
    composed with normal Python so the data flow is obvious to readers.
    """

    name: str
    func: Callable[..., Any]
    stages: tuple = ()
    description: str = ""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        log.info(f"PIPELINE  start  name={self.name}  stages={len(self.stages)}")
        t0 = time.time()
        out = self.func(*args, **kwargs)
        log.info(
            f"PIPELINE  done   name={self.name}  "
            f"elapsed={time.time()-t0:.1f}s"
        )
        return out

    run = __call__   # alias

    # ------------------------------------------------------------------
    # DAG inspection
    # ------------------------------------------------------------------
    def dag(self) -> dict:
        """Return ``{stage: list_of_upstream_stages}`` for every Stage in
        this Pipeline's ``stages``.  Includes transitive dependencies that
        weren't explicitly listed."""
        seen: dict = {}
        stack = list(self.stages)
        while stack:
            s = stack.pop()
            if s in seen:
                continue
            seen[s] = list(s.depends_on)
            for d in s.depends_on:
                if d not in seen:
                    stack.append(d)
        return seen

    def topological_order(self) -> list:
        """Stages in dependency order.  Raises ``ValueError`` on cycles."""
        graph = self.dag()
        in_degree = {s: 0 for s in graph}
        for s, deps in graph.items():
            for d in deps:
                in_degree[s] += 1
        ready = [s for s, n in in_degree.items() if n == 0]
        order: list = []
        # Stable-traversal: keep declaration order among the no-dep set
        while ready:
            ready.sort(key=lambda s: s.name)
            s = ready.pop(0)
            order.append(s)
            for other, deps in graph.items():
                if s in deps:
                    in_degree[other] -= 1
                    if in_degree[other] == 0:
                        ready.append(other)
        if len(order) != len(graph):
            cyc = [s.name for s in graph if s not in order]
            raise ValueError(f"Cycle detected in pipeline DAG: {cyc}")
        return order

    def show_graph(self, *, indent: str = "  ") -> str:
        """ASCII rendering of the pipeline's DAG.  Returns the string and
        also prints it.  No execution."""
        order = self.topological_order()
        idx = {s: i for i, s in enumerate(order)}
        lines = [
            f"# Pipeline: {self.name}",
            f"#   {self.description}" if self.description else "",
            f"#   {len(order)} stages, "
            f"{sum(s.cpu for s in order)} cpu-units total",
            "",
        ]
        for i, s in enumerate(order):
            dep_idx = sorted(idx[d] for d in s.depends_on if d in idx)
            arrow = (
                " ← " + ", ".join(f"#{j}" for j in dep_idx)
                if dep_idx else ""
            )
            lines.append(
                f"{indent}#{i:<2d} {s.name:<22s} "
                f"[{s.image}]  cpu={s.cpu} ram={s.ram_gb}GB  cache={'Y' if s.cache else 'N'}"
                f"{arrow}"
            )
        out = "\n".join(line for line in lines if line is not None)
        print(out)
        return out

    def dry_run(self) -> dict:
        """Return a structured plan of what would execute, without running.

        Cheap inspection: just walks the declared DAG and returns
        names + resource sums.  Does NOT touch Docker.
        """
        order = self.topological_order()
        return {
            "pipeline": self.name,
            "description": self.description,
            "n_stages": len(order),
            "total_cpu": sum(s.cpu for s in order),
            "total_ram_gb": sum(s.ram_gb for s in order),
            "stages": [
                {
                    "name": s.name,
                    "image": s.image,
                    "cpu": s.cpu,
                    "ram_gb": s.ram_gb,
                    "cache": s.cache,
                    "depends_on": [d.name for d in s.depends_on],
                }
                for s in order
            ],
        }


def pipeline(
    *,
    stages: Iterable[Stage] = (),
    name: Optional[str] = None,
    description: str = "",
) -> Callable[[Callable], Pipeline]:
    """Decorator: turn a Python function into a named :class:`Pipeline`.

    The decorated function is the pipeline body — bioflow does not
    rewrite or schedule it.  The optional ``stages`` declaration is what
    feeds ``show_graph()`` / ``dry_run()``; pass every Stage that the body
    *intends* to call.  Stages reachable through ``depends_on`` are
    discovered automatically.

    Example
    -------
    >>> @stage(image="prokka:latest", cpu=2, ram_gb=4)
    ... def annotate(g, *, out_dir): ...
    >>> @stage(image="roary:latest", cpu=8, ram_gb=16, depends_on=annotate)
    ... def pangenome(annot_results, *, out_dir): ...
    >>> @pipeline(stages=[annotate, pangenome],
    ...           description="Prokka + Roary pangenome on N genomes")
    ... def comp_genomics(genomes):
    ...     annotated = annotate.map(genomes, parallel="auto")
    ...     return pangenome(annotated)
    """

    def decorator(func: Callable) -> Pipeline:
        deps: tuple = tuple(stages)
        for s in deps:
            if not isinstance(s, Stage):
                raise TypeError(
                    f"pipeline.stages must contain Stage objects; got "
                    f"{type(s).__name__}"
                )
        p = Pipeline(
            name=name or func.__name__,
            func=func,
            stages=deps,
            description=(
                description
                or (func.__doc__ or "").strip().split("\n")[0]
            ),
        )
        functools.update_wrapper(p, func, updated=())
        return p

    return decorator
