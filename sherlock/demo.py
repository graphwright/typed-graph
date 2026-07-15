"""Demo loader for Sherlock JSONL data vendored in this repository."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from graph import Graph
from sherlock.importer import load_story_graph


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
    main()
