# The Typed Graph Saga

## Origins: Medical Literature and High-Stakes Reasoning

This work began as an exploration of Graph RAG for medical literature. It quickly
became clear that the needs of researchers and clinicians marked this as a **"high
stakes" area** of reasoning and retrieval, where errors, ambiguities, or untracked
assumptions could have serious consequences. This realization shaped every design
decision that followed.

Three principles emerged as non-negotiable requirements:

### 1. **Rigorous Typing**

The knowledge graph must use types and type-checking tools as a guard against
meaningless contents. This serves two purposes:

- **At ingestion time**: Types guide parsing of ambiguous input, rejecting malformed
  claims before they pollute the graph.
- **At query time**: Type errors surface as mypy/Pydantic failures during development,
  not as silent corruption in production.

The key insight: *prevention is cheaper than cleanup*. Medical literature contains
thousands of relationship types (treats, contraindicates, metabolizes, encodes,
regulates...). Without strict typing, a graph becomes a stringly-typed swamp where
"DrugX treats DiseaseY" and "DiseaseY treats DrugX" are both syntactically valid.

### 2. **Canonical IDs**

The medical field has accumulated authoritative ontologies for diseases (ICD-10,
SNOMED), drugs (RxNorm), genes (HGNC), organisms (NCBI Taxonomy), and more. Using
these ontology references as **canonical instance IDs** makes cross-source merging
straightforward:

- Two papers both mention "diabetes mellitus" → same entity (`icd10:E11`)
- One paper says "metformin", another says "Glucophage" → same drug (`rxnorm:6809`)
- Entity resolution becomes a **lookup**, not a heuristic matching problem

The alternative — generating UUIDs or synthetic keys — creates an unbounded merge
problem: every new source requires fuzzy matching against the entire existing graph.
Canonical IDs from trusted ontologies close off that complexity entirely.

### 3. **Provenance**

Every claim in a medical knowledge graph must be traceable back to its source. This
is not optional:

- **For validation**: Is this claim from a peer-reviewed RCT, or a blog post?
- **For dispute resolution**: Two papers contradict each other — which one is more
  recent, more authoritative, or based on a larger study?
- **For compliance**: Regulatory frameworks (HIPAA, GDPR, FDA guidance) often require
  full audit trails.

Critically, the provenance model must distinguish **grounded facts** (backed by a
traceable source) from **hypothetical statements** (introduced by a reasoner or
user). Both are legitimate graph contents, but mixing them without distinction is a
design error. See Hard Rule R10 in `formal-defns.md`.

---

## The Sherlock Detour: A Bounded Testbed

Medical literature presented a classic bootstrapping problem: the domain is vast,
the datasets are proprietary or regulated, and the correctness criteria are subtle
(what counts as a "correct" answer when papers disagree?). Before tackling that, the
formalism needed a **bounded, checkable domain** where:

1. The "correct" answers are known (the stories resolve every mystery)
2. The dataset is small enough to inspect by hand
3. The reasoning challenge is non-trivial (requires deduction + probabilistic ranking)
4. Success is unambiguous (did we find the photograph, or not?)

The **Sherlock Holmes canon** fit perfectly. Specifically, *A Scandal in Bohemia*
poses a concrete mystery: **Where is the incriminating photograph hidden?**

The story provides:
- **112 entities** (people, places, objects)
- **161 events** (actions with participants, locations, times)
- **46 moments** (temporal markers)
- **394 relationship triplets** (person X possesses object Y, event Z happened in
  location W, etc.)

The Baker Street Wiki (https://bakerstreet.fandom.com) serves as the **ontology
authority**, providing canonical entity IDs. This mirrors the medical-literature use
case: if two events both reference "Irene Adler," they use the same entity ID
(`wiki:Irene_Adler`), no fuzzy matching needed.

### The Two-Stage Reasoning Pipeline

The mystery demonstrates the split between **deterministic logic** and **probabilistic
ranking**:

#### Stage 1: Deterministic Solve (Horn Clauses via Datalog)

The `datalog.Engine` applies rules like:

```
physically_in(Object, Place) :-
    possesses(Person, Object),
    associated_with(Person, Place),
    happened_in(Event, Place),
    involves(Event, Person).
```

Given asserted facts from the story (Irene possesses the photo, the reveal-coincidence
event happened at Briony Lodge, etc.), the engine derives **candidate hiding places**.

On the current dataset, deduction narrows the set but **does not uniquely determine**
the answer — multiple places are logically possible. This is realistic: pure logic
often underdetermines conclusions.

#### Stage 2: Probabilistic Ranking (ProbLog)

The ProbLog layer introduces **primitive random variables** with curated probabilities:

```prolog
0.98::photo_in_place(Place) :-
    reveal_coincidence_place(Place),
    alarm_reveal_moment,
    carry_event_feasible.
```

Conditioning on evidence (observations from the story), ProbLog ranks candidates by
posterior probability. The highest-ranked candidate is Briony Lodge's sitting-room
recess — the correct answer from the story.

This two-stage design is the intended pattern for medical reasoning as well:
deterministic rules for what **must** follow (drug metabolism pathways, contraindication
logic), probabilistic ranking for what is **most likely** when the graph underdetermines
(treatment selection given patient history, diagnostic ranking given symptoms).

---

## What Was Learned

### 1. **Schema/Instance Separation is Load-Bearing**

The strict partition between types (schema, fixed at design time) and instances
(data, populated at runtime) prevented an entire class of bugs. Specifically:

- Domain/range violations are caught by Pydantic at **construction time**, not at
  query time after corrupt data is already in the graph.
- Traits (Symmetric, Transitive, Inverse) belong to **predicate types**, not
  individual statements — enforced by the class hierarchy. See R1 in `formal-defns.md`.

The medical literature use case demands this discipline even more: a graph with
10,000 predicate types cannot rely on manual review to catch type errors.

### 2. **Higher-Order Predication is Essential**

The ability to predicate **about statements** (not just entities) is required for
epistemic reasoning:

```python
class Believes(BaseStatement[Person, AnyStatement]):
    """A person's attitude toward a proposition."""

# Watson believes (Irene possesses the photograph)
belief = Believes(
    subject=watson,
    object_=Possesses(subject=irene, object_=photo)
)
```

This captures **nested belief** without reification (no need to invent intermediate
"proposition" entities). Medical literature needs the same: "Paper X contradicts
Paper Y," "Author A disputes Claim B," "Meta-analysis C synthesizes [list of studies]."

The design choice: `BaseStatement` is a full member of V (the instance set), so it
can appear as a subject or object of another statement. See the E ⊆ V property in
`formal-defns.md`.

### 3. **Provenance Merging is Critical**

When multiple sources assert the same fact, their provenance records must **merge**,
not overwrite:

```python
# Source 1: hr.csv says Alice works for Acme
stmt1 = WorksFor(..., provenance=(Provenance(source="hr.csv", ...),))

# Source 2: wiki says the same thing
stmt2 = WorksFor(..., provenance=(Provenance(source="wiki", ...),))

# Engine merges: surviving statement has *both* provenance records
merged.provenance == (Provenance(source="hr.csv", ...), Provenance(source="wiki", ...))
```

This was not obvious upfront — early versions kept only the first-seen provenance,
silently discarding corroboration. The Sherlock domain exposed the error: when the
dataset and the story text both assert a fact, the merged statement should cite both.

Medical literature makes this even more important: a claim corroborated by five papers
should carry all five citations, not just the first.

### 4. **Ungrounded Hypotheticals are Valid Graph Contents**

The graph must accommodate **what-if reasoning** — statements introduced by a reasoner
or user that have no external source. The design choice: `provenance` is **optional**,
with an explicit `None` state meaning "ungrounded."

The Sherlock demo generates hypothetical candidates ("what if the photo is in the
safe?") before evaluating them. Medical reasoning needs the same: "What if we treat
with DrugX instead of DrugY?" generates a hypothetical treatment edge, reasons over
it, then possibly retracts it.

The discipline: queries can **restrict to the grounded subgraph** when only
source-backed facts are acceptable, or **admit ungrounded statements** when exploring
hypotheticals. Both are legitimate, and the distinction must be explicit.

---

## Sherlock Implementation Details

### Data Ingestion

The `sherlock.importer.load_story_graph` function reads four JSONL files:

- **bohemia_entities.jsonl** (112 lines): entities with types, names, canonical IDs
- **bohemia_events.jsonl** (161 lines): events with participants, locations, times
- **bohemia_moments.jsonl** (46 lines): temporal markers
- **bohemia_triplets.jsonl** (394 lines): binary relationships (subject, predicate, object)

Each entity gets a `wiki:` prefixed ID (e.g., `wiki:Irene_Adler`). Missing entities
referenced in relationships are created as **provisional placeholders** — the
`provisional: ClassVar[bool] = True` field marks them for later backfilling.

Relationships are mapped to typed `BaseStatement` subclasses:

```python
Possesses(subject=irene, object_=photo, truth_status="asserted_true", provenance=(...))
HappenedIn(subject=reveal_event, object_=briony_lodge, ...)
Involves(subject=reveal_event, object_=irene, ...)
```

### Querying the Graph

The `graph.Graph` class provides indexed lookups:

```python
g = Graph.from_module(sherlock.entire_graph)

# Forward edges: what does Irene possess?
possessions = g.edges_from("wiki:Irene_Adler", pred_type=Possesses)

# Backward edges: who possesses the photo?
possessors = g.edges_to("wiki:photograph", pred_type=Possesses)

# BFS traversal: all entities within 2 hops of Holmes
layers = g.bfs(["wiki:Sherlock_Holmes"], max_hops=2)
```

The graph is fully in-memory — no database, no query language parser. For the
Sherlock scale (713 facts), this is instant. For medical literature (millions of
facts), a persistent store becomes necessary, but the **typed-graph formalism
remains unchanged**.

### The Demo: Solving the Mystery

Run with:

```bash
SOLVE_MYSTERY_PROBLOG=1 uv run python -m sherlock.demo
```

The demo:
1. Loads the 713-fact graph
2. Applies deterministic rules (Datalog) to derive candidate hiding places
3. Constructs a ProbLog program with primitives + evidence
4. Evaluates marginal probabilities for each candidate
5. Returns the top-ranked location: **Briony Lodge sitting-room recess**

This matches the story's resolution. The demo is fully reproducible — same input,
same ranked output — and the provenance chain for every derived fact is traceable.

---

## Next: Medical Literature

The Sherlock domain validated the formalism. The next step is applying it to the
original motivating use case: **medical literature knowledge graphs**.

Key differences from Sherlock:

### Scale
- **Entities**: millions (diseases, drugs, genes, proteins, organisms, procedures)
- **Relationships**: billions (drug-drug interactions, gene regulation, treatment
  efficacy, contraindications)
- **Sources**: thousands of papers, databases, clinical trial registries

### Ontology Integration
- **Diseases**: ICD-10, SNOMED CT, MeSH, OMIM
- **Drugs**: RxNorm, ATC, DrugBank, ChEMBL
- **Genes**: HGNC, Ensembl, NCBI Gene
- **Cross-references**: UMLS ties them together

### Temporal Dynamics
Medical knowledge evolves:
- A drug approved in 2020 was unknown in 2015
- A claim retracted in 2023 was asserted in 2021
- Treatment guidelines change based on new evidence

The `Provenance` model must track **as-of dates** (see DECISIONS.md D5).

### Epistemic Complexity
Papers disagree. Meta-analyses synthesize contradictory findings. Clinical guidelines
weigh evidence quality (RCT > cohort study > case report). The graph must support:

- **Truth status** (asserted_true, asserted_false, disputed, retracted)
- **Confidence scores** (attached to provenance records)
- **Higher-order dispute predicates** (Paper X contradicts Paper Y)

### Reasoning Challenges
- **Drug interaction checking**: multi-hop transitive closure over metabolism pathways
- **Diagnostic ranking**: probabilistic reasoning over symptom → disease edges
- **Treatment selection**: conditioning on patient history + contraindications
- **Literature synthesis**: merge findings from multiple papers, weight by study design

All of these are in scope for the typed-graph formalism. The Sherlock demo proved the
engine works at small scale; the medical domain will stress-test it at production scale.

### Persistent Storage

The in-memory `Graph` will not scale to millions of entities. Options under
consideration:

- **SQLite** with FTS5 for small deployments (single-file, no server)
- **PostgreSQL** with ltree/GIN indexes for medium scale
- **Neo4j** or **DGraph** for graph-native query optimization
- **Hybrid**: store entities in Postgres, derive the edge set on demand via rules

The critical constraint: whatever the storage layer, it must **preserve the typed-graph
invariants** (R1–R10 in `formal-defns.md`). A relational schema that allows
domain/range violations or mixes schema and instance is a non-starter.

---

## Lessons for Future Domains

The Sherlock experience generalizes:

### Start with a Bounded Testbed
Before tackling a massive, messy domain, find a **miniature version** where:
- Correct answers are known
- The dataset fits in your head
- The reasoning challenge is representative of the real problem

For typed-graph, that was *A Scandal in Bohemia*. For your domain, it might be a
single research paper, a toy dataset, or a well-understood case study.

### Type Everything, Early
Stringly-typed graphs are a tar pit. Adding types after the fact is painful. The
typed-graph approach: define types **first** (the schema layer), then populate
instances. Pydantic + mypy enforce correctness from day one.

### Provenance is Not Optional
If you cannot trace a claim back to its source, the graph is a liability, not an
asset. Build provenance tracking into the data model from the start (see R10).

### Separate Deterministic from Probabilistic
Horn clauses (Datalog) are transparent and truth-preserving. Probabilistic models
(ProbLog, Bayesian networks) are opaque and require tuning. Keep them **separate**:
use logic for what must follow, use probabilities for ranking when logic underdetermines.

The Sherlock two-stage pipeline is the intended pattern for all typed-graph
applications.

---

## Current Status

**Completed:**
- Formal model (4-tuple, Hard Rules R1–R10)
- Python implementation (base, rules, datalog, serialize, graph) in `tg-core`
- Sherlock Holmes domain (schema, importer, 713-fact dataset, ProbLog adapter)
- Deterministic + probabilistic mystery-solving demo
- 96 tests covering core + domain functionality

**In Progress:**
- Extracting `tg-core` as a reusable package (editable install from `../tg-core`)
- Documenting design decisions (DECISIONS.md)

**Next:**
- Medical literature domain schema
- Ontology integration (ICD-10, RxNorm, HGNC)
- Persistent storage layer
- Query API (BFS-QL or equivalent)
- Ingestion pipeline (PubMed, clinical trial registries)

The Sherlock detour proved the formalism works. Now we return to the original goal:
**high-stakes reasoning over medical literature**, with the confidence that the
foundation is solid.
