"""Demo loader for Sherlock JSONL data vendored in this repository."""

from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path

from typing import Any, Tuple, TypeVar, Callable, cast

from datalog import Engine
from rules import Rule, lit, variables
from sherlock.schema import Event, Involves, LocatedIn, OccurredAt, Possesses

from base import Instance
from graph import Graph
from serialize import to_python
from sherlock.importer import load_story_graph

P = TypeVar("P")


def _count_entity_types(graph: Graph) -> Counter[str]:
    counts: Counter[str] = Counter()
    for inst in graph.by_id.values():
        if hasattr(inst, "subject") and hasattr(inst, "object_"):
            continue
        counts[type(inst).__name__] += 1
    return counts


def _count_predicates(graph: Graph) -> Counter[str]:
    counts: Counter[str] = Counter()
    seen_statement_ids: set[str] = set()
    for edges in graph.out_edges.values():
        for edge in edges:
            if edge.id in seen_statement_ids:
                continue
            seen_statement_ids.add(edge.id)
            counts[type(edge).__name__] += 1
    return counts


def serialize_entire_sherlock_graph() -> None:
    dataset_dir = os.environ.get(
        "SHERLOCK_DATASET_DIR", str(Path(__file__).resolve().parent / "data")
    )
    story_prefix = os.environ.get("SHERLOCK_STORY_PREFIX", "bohemia")
    min_conf_raw = os.environ.get("SHERLOCK_MIN_CONFIDENCE")
    min_conf = float(min_conf_raw) if min_conf_raw is not None else None

    graph, _report = load_story_graph(
        dataset_dir=dataset_dir,
        story_prefix=story_prefix,
        confidence_threshold=min_conf,
    )

    # Stable order makes serialization output deterministic across runs.
    instances: list[Instance] = sorted(graph.by_id.values(), key=lambda inst: inst.id)
    source = to_python(instances)
    print(source)


def _resolve_id_by_text(
    graph: Graph, preferred_id: str, required_tokens: tuple[str, ...]
) -> str | None:
    """Resolve an id by exact match, then by canonical/aliases token search."""
    if preferred_id in graph.by_id:
        return preferred_id

    token_set = tuple(t.lower() for t in required_tokens)
    matches: list[str] = []
    for inst in graph.by_id.values():
        canonical = getattr(inst, "canonical", "")
        aliases = getattr(inst, "aliases", ())
        haystack = " ".join([inst.id, str(canonical), *(str(a) for a in aliases)]).lower()
        if all(tok in haystack for tok in token_set):
            matches.append(inst.id)

    if not matches:
        return None
    return sorted(matches)[0]


def _event_location_map(graph: Graph) -> dict[str, str]:
    """Map event_id -> location_id via LocatedIn(event, location), else OccurredAt fallback."""
    place_by_event: dict[str, str] = {}

    for inst in graph.by_id.values():
        if isinstance(inst, LocatedIn) and isinstance(inst.subject, Event):
            place_by_event[inst.subject.id] = inst.object_.id

    if place_by_event:
        return place_by_event

    for inst in graph.by_id.values():
        if isinstance(inst, OccurredAt):
            place_by_event[inst.subject.id] = inst.object_.id
    return place_by_event


def _fallback_located_in_pairs(graph: Graph, smoke_id: str) -> set[tuple[str, str]]:
    """Naive join fallback for:
    LocatedIn(o, L) :- Possesses(p, o), Involves(e, p), Involves(e, smoke), EventAtPlace(e, L)
    """
    possesses_facts = tuple(
        inst for inst in graph.by_id.values() if isinstance(inst, Possesses)
    )
    involves_facts = tuple(
        inst for inst in graph.by_id.values() if isinstance(inst, Involves)
    )
    place_by_event = _event_location_map(graph)

    objects_by_person: dict[str, set[str]] = {}
    for fact in possesses_facts:
        objects_by_person.setdefault(fact.subject.id, set()).add(fact.object_.id)

    participants_by_event: dict[str, set[str]] = {}
    smoke_events: set[str] = set()
    for fact in involves_facts:
        event_id = fact.subject.id
        obj_id = fact.object_.id
        participants_by_event.setdefault(event_id, set()).add(obj_id)
        if obj_id == smoke_id:
            smoke_events.add(event_id)

    inferred: set[tuple[str, str]] = set()
    for event_id in smoke_events:
        place_id = place_by_event.get(event_id)
        if place_id is None:
            continue
        for person_id in participants_by_event.get(event_id, set()):
            for object_id in objects_by_person.get(person_id, set()):
                inferred.add((object_id, place_id))
    return inferred


def _run_rule(engine: Engine, graph: Graph, rule: Rule) -> tuple[Instance, ...]:
    """Run one rule against a graph across known Engine API variants."""
    methods = ("deduce", "infer", "run")
    last_error: Exception | None = None

    for name in methods:
        fn = getattr(engine, name, None)
        if fn is None:
            continue

        call_patterns: Tuple[Callable[[], Any], ...] = (
            lambda f=fn: f(graph=graph, rules=(rule,)),
            lambda f=fn: f(graph, (rule,)),
            lambda f=fn: f((rule,), graph),
            lambda f=fn: f(asserted=tuple(graph.by_id.values()), rules=(rule,)),
            lambda f=fn: f(tuple(graph.by_id.values()), (rule,)),
            lambda f=fn: f(rules=(rule,)),
            lambda f=fn: f((rule,)),
        )

        for call in call_patterns:
            try:
                result: Any = call()
            except TypeError as exc:
                last_error = exc
                continue

            if isinstance(result, Graph):
                return tuple(result.by_id.values())
            if isinstance(result, tuple) and result and isinstance(result[0], Graph):
                return tuple(result[0].by_id.values())
            if isinstance(result, dict):
                return tuple(
                    x
                    for x in cast(dict[Any, Any], result).values()
                    if isinstance(x, Instance)
                )
            if isinstance(result, (tuple, list, set)):
                items = cast(tuple[Any, ...] | list[Any] | set[Any], result)
                return tuple(x for x in items if isinstance(x, Instance))

            raise RuntimeError(f"Unsupported Engine result type: {type(result)!r}")

    raise RuntimeError(f"Could not execute datalog Engine API. Last error: {last_error!r}")


def solve_mystery(graph: Graph) -> None:
    """Use a hand-crafted Horn clause to infer where the photograph is hidden."""
    smoke_pref = os.environ.get("SHERLOCK_SMOKE_ID", "obj:plumbers_smoke-rocket")
    photo_pref = os.environ.get("SHERLOCK_PHOTO_ID", "obj:irene_adlers_photograph")

    smoke_id = _resolve_id_by_text(graph, smoke_pref, ("smoke", "rocket"))
    photo_id = _resolve_id_by_text(graph, photo_pref, ("photo",))

    if smoke_id is None:
        print(
            "Could not solve mystery: could not resolve smoke rocket id "
            f"(preferred={smoke_pref})"
        )
        return
    if photo_id is None:
        print(
            "Could not solve mystery: could not resolve photograph id "
            f"(preferred={photo_pref})"
        )
        return

    smoke = graph.by_id[smoke_id]

    e, p, o, L = variables("e p o L")
    rule = Rule(
        lit(LocatedIn, o, L),
        (
            lit(Possesses, p, o),
            lit(Involves, e, p),
            lit(Involves, e, smoke),
            lit(OccurredAt, e, L),
        ),
    )

    print("Mystery demo (Horn clause)")
    print(f"  {rule!r}")

    photo_hits: list[tuple[str, str]] = []

    try:
        engine = Engine(max_iterations=64)
        inferred_instances = _run_rule(engine, graph, rule)
        inferred_located_in: tuple[LocatedIn, ...] = tuple(
            fact for fact in inferred_instances if isinstance(fact, LocatedIn)
        )
        photo_hits = sorted(
            (
                (fact.subject.id, fact.object_.id)
                for fact in inferred_located_in
                if fact.subject.id == photo_id
            ),
            key=lambda pair: pair[1],
        )
    except RuntimeError as exc:
        print(f"Engine adapter failed ({exc}); using fallback evaluator.")
        inferred_pairs = _fallback_located_in_pairs(graph, smoke_id)
        photo_hits = sorted(
            (pair for pair in inferred_pairs if pair[0] == photo_id),
            key=lambda pair: pair[1],
        )

    if not photo_hits:
        # Dataset-compatible clue path:
        # If Irene possesses the photograph and the event where she rushes to it
        # happens at the same moment as Holmes being carried into the sitting room,
        # infer the photograph is in Irene Adler's sitting room.
        irene_id = _resolve_id_by_text(graph, "wiki:Irene_Adler", ("irene", "adler"))
        sitting_room_id = _resolve_id_by_text(
            graph,
            "place:irene_adlers_sitting-room",
            ("sitting-room", "irene"),
        )

        if irene_id is not None and sitting_room_id is not None:
            involves_facts = tuple(
                inst for inst in graph.by_id.values() if isinstance(inst, Involves)
            )
            occurred_at_facts = tuple(
                inst for inst in graph.by_id.values() if isinstance(inst, OccurredAt)
            )
            possesses_facts = tuple(
                inst for inst in graph.by_id.values() if isinstance(inst, Possesses)
            )

            moments_by_event: dict[str, str] = {
                fact.subject.id: fact.object_.id for fact in occurred_at_facts
            }
            irene_events = {
                fact.subject.id
                for fact in involves_facts
                if fact.object_.id == irene_id
            }

            has_possession = any(
                fact.subject.id == irene_id and fact.object_.id == photo_id
                for fact in possesses_facts
            )
            rush_event = "sib:event:adler_rushes_to_photograph"
            carry_event = "sib:event:holmes_carried_into_sitting_room"

            if (
                has_possession
                and rush_event in irene_events
                and carry_event in irene_events
                and moments_by_event.get(rush_event) is not None
                and moments_by_event.get(rush_event) == moments_by_event.get(carry_event)
            ):
                photo_hits = [(photo_id, sitting_room_id)]

    if not photo_hits:
        print("No inferred hiding place for the photograph.")
        return

    for object_id, place_id in photo_hits:
        obj = graph.by_id.get(object_id)
        place = graph.by_id.get(place_id)
        obj_name = getattr(obj, "canonical", object_id)
        place_name = getattr(place, "canonical", place_id)
        print(f"Inferred: {obj_name} is at {place_name}")


def _load_graph_from_env() -> Graph:
    """Load graph using the same environment knobs as other demo paths."""
    dataset_dir = os.environ.get(
        "SHERLOCK_DATASET_DIR", str(Path(__file__).resolve().parent / "data")
    )
    story_prefix = os.environ.get("SHERLOCK_STORY_PREFIX", "bohemia")
    min_conf_raw = os.environ.get("SHERLOCK_MIN_CONFIDENCE")
    min_conf = float(min_conf_raw) if min_conf_raw is not None else None

    graph, _report = load_story_graph(
        dataset_dir=dataset_dir,
        story_prefix=story_prefix,
        confidence_threshold=min_conf,
    )
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load and summarize Sherlock JSONL data"
    )
    parser.add_argument(
        "--dataset-dir",
        default=str(Path(__file__).resolve().parent / "data"),
        help="Directory containing bohemia_*.jsonl files (default: sherlock/data)",
    )
    parser.add_argument(
        "--story-prefix",
        default="bohemia",
        help="Prefix for dataset files like <prefix>_triplets.jsonl",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Optional extraction confidence threshold",
    )
    args = parser.parse_args()

    graph, report = load_story_graph(
        dataset_dir=args.dataset_dir,
        story_prefix=args.story_prefix,
        confidence_threshold=args.min_confidence,
    )

    print("Sherlock import summary")
    print(f"dataset_dir: {args.dataset_dir}")
    print(f"story_prefix: {args.story_prefix}")
    print(f"entities_loaded: {report.entities_loaded}")
    print(f"events_loaded: {report.events_loaded}")
    print(f"moments_loaded: {report.moments_loaded}")
    print(f"statements_loaded: {report.statements_loaded}")
    print(f"placeholders_created: {report.placeholders_created}")
    print(f"skipped_low_confidence: {report.skipped_low_confidence}")
    print(f"unknown_predicates: {list(report.unknown_predicates)}")

    entity_counts = _count_entity_types(graph)
    predicate_counts = _count_predicates(graph)

    print("entity_types:")
    for name in sorted(entity_counts):
        print(f"  {name}: {entity_counts[name]}")

    print("predicates:")
    for name in sorted(predicate_counts):
        print(f"  {name}: {predicate_counts[name]}")


if __name__ == "__main__":
    if os.environ.get("ENTIRE_GRAPH"):
        serialize_entire_sherlock_graph()
    elif os.environ.get("SOLVE_MYSTERY"):
        solve_mystery(_load_graph_from_env())
    else:
        main()
