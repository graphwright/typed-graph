"""Throwaway FastAPI wrapper around graph.py's Graph, built to give the
compose -> Kubernetes exercise a real process with a real port to reach.

Not part of the tg-core package and not meant to be maintained as one --
see k8s-exercise/README.md.
"""

import example
from base import Provenance
from example import Owns, WorksFor, acme, car
from fastapi import FastAPI, HTTPException
from graph import Graph

app = FastAPI(title="tg-core graph API (learning exercise)", root_path="/api/v1")

# example.py's own statements are local to main(); build a couple here so the
# read endpoints below have edges to actually traverse.
_prov = Provenance(source="k8s-exercise/app.py", extraction_method="manual")
g = Graph.from_module(example)
g.extend(
    [
        WorksFor(
            id="alice-works_for-acme",
            subject=example.alice,
            object_=acme,
            truth_status="asserted_true",
            provenance=(_prov,),
        ),
        Owns(
            id="acme-owns-car1",
            subject=acme,
            object_=car,
            truth_status="asserted_true",
            provenance=(_prov,),
        ),
    ]
)


def _require(entity_id: str) -> None:
    if g.get(entity_id) is None:
        raise HTTPException(status_code=404, detail=f"no such entity: {entity_id}")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/entities/{entity_id}")
def get_entity(entity_id: str) -> dict[str, str]:
    _require(entity_id)
    return {"id": entity_id, "description": g.describe(entity_id)}


@app.get("/entities/{entity_id}/edges")
def get_edges(entity_id: str, direction: str = "out") -> list[dict[str, str]]:
    _require(entity_id)
    edges = g.edges_from(entity_id) if direction == "out" else g.edges_to(entity_id)
    return [
        {"id": e.id, "type": type(e).__name__, "description": str(e)} for e in edges
    ]


@app.get("/bfs")
def bfs(seed: str, max_hops: int = 2) -> list[list[str]]:
    _require(seed)
    return [sorted(layer) for layer in g.bfs([seed], max_hops=max_hops)]
