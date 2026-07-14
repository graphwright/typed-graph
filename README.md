# Informal typed graph specification

The formal definition of a typed graph appears in the file `formal-defns.md`.
The intention here is to define an informal definition that will be
comfortable for Python developers, framed as a base package that can be
extended to accomodate different knowledge domains.

The 4-tuple $(T, \Phi, V, \tau)$ is realized as a small Pydantic class hierarchy in
`base.py`: an `Instance` root (membership in $V$) with two disjoint subclasses,
`EntityInstance` and `BaseStatement`. `BaseStatement` is generic over its subject and
object types, so a predicate's domain and range are ordinary type annotations checked
by mypy and Pydantic. A worked domain (`Person`, `Organization`, `WorksFor`) lives in
`example.py`.

## Domain and range

$\text{dom}(p)$ and $\text{ran}(p)$ are **sets** of types. A predicate binds them as
the type arguments of `BaseStatement`. When a set has one member, that's a single
type; when it has several, write them as a `|` union — the union *is* the set:

```python
# Singleton domain and range: dom = {Person}, ran = {Organization}
class WorksFor(BaseStatement[Person, Organization]): ...

# Multi-member sets via |: dom = {Person, Organization}, ran = {Vehicle}
class Owns(BaseStatement[Person | Organization, Vehicle]): ...
```

Use `|` anywhere a domain or range legitimately admits more than one type; the members
may overlap between domain and range, and either side may be widened this way
independently. mypy rejects a subject or object outside the declared set statically,
and Pydantic rejects it at construction — no hand-written validation. The subject side
must be entity types; the object side may also include a `BaseStatement` subclass,
which is how a predicate ranges over other statements (higher-order predication).

### Higher-order predication

When a predicate's object is itself a statement, its **concrete predicate type must be
preserved** — `Believes(alice, WorksFor(...))` should keep the object a `WorksFor`, so
you can still ask its traits, its inverse, or serialize it. For a range of "any
statement", declare it with `AnyStatement` (exported from `base`, an
`InstanceOf[BaseStatement]`):

```python
from base import AnyStatement, BaseStatement

class Believes(BaseStatement[Person, AnyStatement]):
    """dom = {Person}, ran = any statement (type preserved)."""
```

`AnyStatement` validates by `isinstance` and stores the object unchanged. A plain
`BaseStatement` / `BaseStatement[Any, Any]` range would instead rebuild the object as
the base class and lose its type. (Trade-off: an object given as a raw dict is
rejected — pass a real instance, or reconstruct one via the loader.)

## Traits

A **trait** is a declarative semantic property of a *predicate type* — it belongs to
the type, never to an individual statement (Hard Rule R1). In this package traits are
realized as **mixin classes** inherited alongside `BaseStatement`. The unparameterized
traits are plain marker classes; `Inverse` is generic, parameterized by the partner
predicate type.

> The marker traits and `Inverse` / `get_inverse` below are implemented in `base.py`;
> the snippets show how a predicate type opts in. `Rule` is realized differently —
> as Python objects in `rules.py` evaluated by `datalog.py`, not as a mixin — see the
> last subsection.

### Marker traits

```python
class Symmetric: ...
class Transitive: ...
class Functional: ...          # each subject has at most one object
class InverseFunctional: ...   # each object has at most one subject
```

A predicate opts in simply by inheriting the mixin alongside the typed base. Because
traits are ordinary base classes, they are introspectable at runtime with
`issubclass`:

```python
class Knows(BaseStatement[Person, Person], Symmetric):
    """Knows(x, y) implies Knows(y, x)."""

class ReportsTo(BaseStatement[Person, Person], Transitive, Functional):
    """ReportsTo is transitive, and each person reports to at most one other."""

issubclass(Knows, Symmetric)          # True
issubclass(ReportsTo, Transitive)     # True
issubclass(WorksFor, Symmetric)       # False
```

### Inverse(p') — the parameterized trait

`Inverse` is a generic mixin parameterized by the partner predicate type. Declaring
`ChildOf` as the inverse of `ParentOf` means `ParentOf(x, y)` entails `ChildOf(y, x)`:

```python
from typing import Generic, TypeVar

P = TypeVar("P", bound="BaseStatement")

class Inverse(Generic[P]): ...

class ParentOf(BaseStatement[Person, Person]):
    """ParentOf(x, y): x is a parent of y."""

class ChildOf(BaseStatement[Person, Person], Inverse[ParentOf]):
    """ChildOf(y, x): y is a child of x — the inverse of ParentOf."""
```

A helper resolves the declared partner from the type parameter:

```python
def get_inverse(stmt_type: type[BaseStatement]) -> type[BaseStatement] | None:
    """Return the partner predicate type if `stmt_type` declares Inverse, else None."""
    ...

get_inverse(ChildOf)   # -> ParentOf
get_inverse(WorksFor)  # -> None
```

### Rule(φ ⇒ ψ) — the escape hatch

`Symmetric`, `Transitive`, and `Inverse` are special cases of Datalog rules that the
type system can express directly:

| Trait          | Equivalent rule                                  |
|----------------|--------------------------------------------------|
| `Transitive`   | `p(x, y) ∧ p(y, z) ⇒ p(x, z)`                    |
| `Symmetric`    | `p(x, y) ⇒ p(y, x)`                              |
| `Inverse(p')`  | `p(x, y) ⇒ p'(y, x)`                             |

Anything that does not fit those named forms — cross-predicate rules, multi-hop
chains, rules with more than two body literals — is expressed with the full `Rule`
form. Unlike the marker traits, `Rule` has no type-level expression; it is built as
plain Python objects and evaluated at runtime:

```python
from rules import Rule, lit, variables
from datalog import Engine

x, y, z = variables("x y z")            # named, untyped logic variables

# Ancestor(x, z) :- Ancestor(x, y), Ancestor(y, z)
transitivity = Rule(lit(Ancestor, x, z), (lit(Ancestor, x, y), lit(Ancestor, y, z)))

eng = Engine()
eng.add_facts(known_ancestor_facts)     # only truth_status == asserted_true
eng.add_rule(transitivity)              # or eng.add_traits(Ancestor)
derived = eng.infer()                   # least fixed point; derived facts are grounded "inferred"
```

`lit(Pred, a, b)` is a rule *literal* (a predicate class with two arguments, each a
`Var` or a concrete `Instance`) — distinct from a `BaseStatement`, which is a member
of $V$. `Engine.add_traits` compiles the marker traits above into their equivalent
rules, so they and hand-written `Rule`s share one evaluator. Each derived head is
constructed through its predicate class, so domain/range are validated exactly as for
any statement. Rules are built directly in Python — there is deliberately no text
grammar or parser. See `formal-defns.md` §Trait vocabulary for the formal treatment.
