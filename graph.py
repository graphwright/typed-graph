"""graph.py — in-memory typed graph over BaseStatement/EntityInstance objects.

No database, no MCP server. Load a set of instances, build indexes, run
BFS and named queries directly against the Python objects.

Typical usage:

    import example
    from graph import Graph

    g = Graph.from_module(example)
    g.bfs(['alice'], max_hops=2)
"""

from __future__ import annotations
import warnings
from collections import defaultdict
from types import ModuleType
from typing import Collection, Iterable, Protocol, TypeAlias, TypeGuard


"""
## Helpers

Duck-typed predicates used during graph construction. Avoiding a direct
import of `EntityInstance` and `BaseStatement` keeps `graph.py` decoupled
from the schema module — any object that has the right attributes will be
indexed correctly.
"""


_WIKI_PREFIX = "https://bakerstreet.fandom.com/wiki/"


class InstanceLike(Protocol):
    """Duck-typed graph instance in V with a stable `id`."""

    id: str


class EntityLike(InstanceLike, Protocol):
    """Duck-typed entity endpoint."""


class StatementLike(InstanceLike, Protocol):
    """Duck-typed predicate instance with subject/object endpoints."""

    subject: EntityLike
    object_: InstanceLike
    truth_status: str
    provenance: tuple[object, ...] | None


# `isinstance` filtering accepts concrete statement classes from external modules;
# `type[object]` keeps this API permissive while StatementLike guards edge payloads.
PredicateClass: TypeAlias = type[object]
PredicateFilter: TypeAlias = PredicateClass | tuple[PredicateClass, ...] | None
PredicateClassSet: TypeAlias = Collection[PredicateClass] | None
TruthFilter: TypeAlias = str | Collection[str] | None
TruthValues: TypeAlias = Collection[str]


def _canonicalize_id(entity_id: str) -> str:
    if entity_id.startswith(_WIKI_PREFIX):
        return "wiki:" + entity_id[len(_WIKI_PREFIX):]
    return entity_id


def _is_instance(obj: object) -> TypeGuard[InstanceLike]:
    return (
        isinstance(getattr(obj, "id", None), str)
        and not callable(obj)
    )


def _is_statement(obj: object) -> TypeGuard[StatementLike]:
    if not _is_instance(obj):
        return False
    if not hasattr(obj, "subject") or not hasattr(obj, "object_") or not hasattr(obj, "truth_status"):
        return False
    subject = getattr(obj, "subject", None)
    object_ = getattr(obj, "object_", None)
    truth_status = getattr(obj, "truth_status", None)
    return _is_instance(subject) and _is_instance(object_) and isinstance(truth_status, str)


def _normalize_truth_filter(truth: TruthFilter) -> set[str] | None:
    if truth is None:
        return None
    if isinstance(truth, str):
        return {truth}
    truth_set = set(truth)
    if not all(isinstance(v, str) for v in truth_set):
        raise TypeError("truth filter values must be strings")
    return truth_set


def _normalize_pred_types(pred_types: PredicateClassSet) -> tuple[PredicateClass, ...] | None:
    """Normalize predicate-type filters; None or empty means no filtering."""
    if pred_types is None:
        return None
    pred_type_tuple = tuple(pred_types)
    return pred_type_tuple if pred_type_tuple else None


"""
## Graph

`Graph` is an in-memory knowledge graph indexed for O(1) neighbor lookup.
Instances are bucketed into three indexes: `by_id` for direct access,
`out_edges` keyed by `subject.id` for forward traversal, and `in_edges`
keyed by `object_.id` for backward traversal.

Because predicate instances are also entities under the unified Statement
model, they are indexed in `by_id` and can themselves appear as the
subject or object of higher-order predicates.
"""


class Graph:

    def __init__(self, instances: Iterable[object]):
        self.by_id: dict[str, InstanceLike] = {}
        self.out_edges: dict[str, list[StatementLike]] = defaultdict(list)   # subject.id -> [stmt]
        self.in_edges: dict[str, list[StatementLike]] = defaultdict(list)    # object_.id -> [stmt]

        for inst in instances:
            if not _is_instance(inst):
                continue
            if inst.id in self.by_id:
                warnings.warn(
                    f"Graph: id collision on {inst.id!r} — overwriting; "
                    "use unique ids per extraction or statement_id() for canonical facts",
                    stacklevel=2,
                )
            self.by_id[inst.id] = inst
            if _is_statement(inst):
                self.out_edges[inst.subject.id].append(inst)
                self.in_edges[inst.object_.id].append(inst)

    @classmethod
    def from_module(cls, module: ModuleType) -> Graph:
        """Build a Graph from all EntityInstance values in a module's namespace."""
        return cls(
            v for v in vars(module).values()
            if _is_instance(v) and not isinstance(v, type)
        )

    def get(self, entity_id: str) -> InstanceLike | None:
        """Return the instance for entity_id, normalizing wiki URLs to canonical form."""
        return self.by_id.get(_canonicalize_id(entity_id))

    def edges_from(
        self,
        entity_id: str,
        pred_type: PredicateFilter = None,
        truth: TruthFilter = None,
    ) -> list[StatementLike]:
        """Outward edges from entity_id, optionally filtered by type and truth_status."""
        edges = self.out_edges.get(_canonicalize_id(entity_id), [])
        if pred_type is not None:
            edges = [e for e in edges if isinstance(e, pred_type)]
        truth_set = _normalize_truth_filter(truth)
        if truth_set is not None:
            edges = [e for e in edges if e.truth_status in truth_set]
        return edges

    def edges_to(
        self,
        entity_id: str,
        pred_type: PredicateFilter = None,
        truth: TruthFilter = None,
    ) -> list[StatementLike]:
        """Inward edges to entity_id, optionally filtered by type and truth_status."""
        edges = self.in_edges.get(_canonicalize_id(entity_id), [])
        if pred_type is not None:
            edges = [e for e in edges if isinstance(e, pred_type)]
        truth_set = _normalize_truth_filter(truth)
        if truth_set is not None:
            edges = [e for e in edges if e.truth_status in truth_set]
        return edges

    def bfs(
        self,
        seed_ids: Collection[str],
        max_hops: int = 3,
        pred_types: PredicateClassSet = None,
        truth_values: TruthValues = ("asserted_true",),
    ) -> list[set[str]]:
        """BFS from seed_ids. Returns one set per hop layer.

        Traverses both outward and inward edges so symmetric predicates (e.g.
        Knows) and reverse relationships (e.g. Events that Involve a person)
        are reachable regardless of the direction they were stored. The
        traversed statement instances are also added to layers so higher-order
        predicates can be followed in later hops.
        """
        visited: set[str] = set(seed_ids)
        frontier: set[str] = set(seed_ids)
        layers: list[set[str]] = [set(seed_ids)]
        pred_type_tuple = _normalize_pred_types(pred_types)

        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for eid in frontier:
                for edge in self.out_edges.get(eid, []):
                    if pred_type_tuple is not None and not isinstance(edge, pred_type_tuple):
                        continue
                    if edge.truth_status not in truth_values:
                        continue
                    for nid in (edge.object_.id, edge.id):
                        if nid not in visited:
                            visited.add(nid)
                            next_frontier.add(nid)
                for edge in self.in_edges.get(eid, []):
                    if pred_type_tuple is not None and not isinstance(edge, pred_type_tuple):
                        continue
                    if edge.truth_status not in truth_values:
                        continue
                    for nid in (edge.subject.id, edge.id):
                        if nid not in visited:
                            visited.add(nid)
                            next_frontier.add(nid)
            layers.append(next_frontier)
            frontier = next_frontier
            if not frontier:
                break

        return layers

    def transitive_closure(
        self,
        entity_id: str,
        pred_type: PredicateClass,
        truth_values: TruthValues = ("asserted_true",),
    ) -> set[str]:
        """All entities reachable from entity_id by following pred_type transitively."""
        visited: set[str] = set()
        frontier: set[str] = {entity_id}
        while frontier:
            next_f: set[str] = set()
            for eid in frontier:
                for edge in self.out_edges.get(eid, []):
                    if not isinstance(edge, pred_type):
                        continue
                    if edge.truth_status not in truth_values:
                        continue
                    obj_id = edge.object_.id
                    if obj_id not in visited:
                        visited.add(obj_id)
                        next_f.add(obj_id)
            frontier = next_f
        return visited

    def describe(self, entity_id: str) -> str:
        """Human-readable description of an instance by id."""
        inst = self.get(entity_id)
        if inst is None:
            return f"<not found: {entity_id}>"
        return str(inst)

    def print_edges(self, edges: Iterable[StatementLike], indent: int = 2) -> None:
        pad = ' ' * indent
        for e in edges:
            print(f"{pad}{e}  [{e.truth_status}]")
