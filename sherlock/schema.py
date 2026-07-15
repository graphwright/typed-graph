"""Typed schema for Sherlock story imports."""

from __future__ import annotations

from typing import Generic, TypeVar

from base import BaseStatement, EntityInstance, Symmetric, Transitive


class SherlockEntity(EntityInstance):
    """Base entity with optional source metadata from the JSONL catalog."""

    canonical: str
    aliases: tuple[str, ...] = ()
    wiki_url: str | None = None
    raw_type: str | None = None


class Person(SherlockEntity):
    """A person in the story world."""


class Organization(SherlockEntity):
    """An organization in the story world."""


class Location(SherlockEntity):
    """A place/location in the story world."""


class Object(SherlockEntity):
    """A tangible or conceptual object in the story world."""


class Event(SherlockEntity):
    """An event node imported from event extraction."""


class Moment(SherlockEntity):
    """A time/moment node imported from timeline extraction."""


class OtherEntity(SherlockEntity):
    """Fallback entity type when the source type is unknown."""


SubjectT = TypeVar("SubjectT", bound=SherlockEntity)
ObjectT = TypeVar("ObjectT", bound=SherlockEntity)


class StoryStatement(BaseStatement[SubjectT, ObjectT], Generic[SubjectT, ObjectT]):
    """Statement enriched with story-extraction metadata from triplet rows."""

    story_id: str
    paragraph_index: int | None = None
    sentence_ids: tuple[int, ...] = ()
    asserting_narrator_id: str | None = None
    extraction_confidence: float | None = None
    narrator_confidence: float | None = None
    raw_extraction_method: str | None = None


class Involves(StoryStatement[Event, Person]):
    """An event involves a person."""


class OccurredAt(StoryStatement[Event, Moment]):
    """An event occurred at a specific moment."""


class Possesses(StoryStatement[Person, Object]):
    """A person possesses an object."""


class AssociatedWith(StoryStatement[Person, Location]):
    """A person is associated with a location."""


class Knows(StoryStatement[Person, Person], Symmetric):
    """A social knowledge relation between two people."""


class LocatedIn(StoryStatement[Location, Location], Transitive):
    """A transitive containment/location relation."""
