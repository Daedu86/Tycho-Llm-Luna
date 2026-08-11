"""Typed semantic grounding between neural interpretation and symbolic models.

The grounding layer records *what the neural system thinks it observed* without
promoting those interpretations into symbolic truth. Confidence here is
extractor confidence attached to an observation, not a posterior belief over
world-model hypotheses. The L2 belief layer can consume these records later.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def _nonempty(name: str, value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{name} must be non-empty")
    return value


def _confidence(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("confidence must be a real number in [0, 1]")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be finite and in [0, 1]")
    return value


def _json_value(value: Any, *, path: str = "value") -> JsonValue:
    """Return a JSON-safe copy, rejecting opaque Python objects.

    Tuples are accepted for ergonomic construction and normalized to lists.
    Dictionary keys must be strings so serialized grounding artifacts remain
    portable across Python and future non-Python consumers.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item, path=f"{path}[]") for item in value]
    if isinstance(value, dict):
        out: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string dictionary key")
            out[key] = _json_value(item, path=f"{path}.{key}")
        return out
    raise ValueError(f"{path} is not JSON-serializable: {type(value).__name__}")


@dataclass(frozen=True)
class EvidenceRef:
    """Pointer to evidence supporting a grounded observation."""

    source: str
    level: int | None = None
    turn: int | None = None
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _nonempty("source", self.source))
        if self.level is not None and self.level < 0:
            raise ValueError("level must be >= 0 when provided")
        if self.turn is not None and self.turn < 0:
            raise ValueError("turn must be >= 0 when provided")

    def to_dict(self) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {"source": self.source}
        if self.level is not None:
            out["level"] = self.level
        if self.turn is not None:
            out["turn"] = self.turn
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class GroundedEntity:
    """An identity proposal anchored to one observation."""

    entity_id: str
    category: str | None = None
    position: tuple[int, int] | None = None
    confidence: float = 1.0
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _nonempty("entity_id", self.entity_id))
        if self.category is not None:
            object.__setattr__(self, "category", _nonempty("category", self.category))
        if self.position is not None:
            if len(self.position) != 2 or any(isinstance(v, bool) or not isinstance(v, int) for v in self.position):
                raise ValueError("position must be a pair of integer coordinates")
            object.__setattr__(self, "position", tuple(self.position))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, JsonValue]:
        out: dict[str, JsonValue] = {
            "entity_id": self.entity_id,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }
        if self.category is not None:
            out["category"] = self.category
        if self.position is not None:
            out["position"] = list(self.position)
        return out


@dataclass(frozen=True)
class GroundedProperty:
    """A proposed property value for a grounded entity."""

    entity_id: str
    name: str
    value: JsonValue
    confidence: float = 1.0
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _nonempty("entity_id", self.entity_id))
        object.__setattr__(self, "name", _nonempty("name", self.name))
        object.__setattr__(self, "value", _json_value(self.value))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "value": self.value,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class GroundedRelation:
    """A proposed relation between two grounded entities."""

    subject_id: str
    predicate: str
    object_id: str
    confidence: float = 1.0
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _nonempty("subject_id", self.subject_id))
        object.__setattr__(self, "predicate", _nonempty("predicate", self.predicate))
        object.__setattr__(self, "object_id", _nonempty("object_id", self.object_id))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "object_id": self.object_id,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class GroundedEvent:
    """A proposed event involving one or more grounded entities."""

    event_type: str
    participants: tuple[str, ...]
    attributes: dict[str, JsonValue] = field(default_factory=dict)
    confidence: float = 1.0
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", _nonempty("event_type", self.event_type))
        participants = tuple(_nonempty("participant", item) for item in self.participants)
        if not participants:
            raise ValueError("participants must contain at least one entity id")
        object.__setattr__(self, "participants", participants)
        normalized = _json_value(self.attributes, path="attributes")
        if not isinstance(normalized, dict):  # defensive: attributes is declared as dict
            raise ValueError("attributes must be a dictionary")
        object.__setattr__(self, "attributes", normalized)
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence", tuple(self.evidence))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "event_type": self.event_type,
            "participants": list(self.participants),
            "attributes": dict(self.attributes),
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class GroundingFrame:
    """Self-consistent semantic interpretation of one observed frame/turn."""

    observation_id: str
    entities: tuple[GroundedEntity, ...] = field(default_factory=tuple)
    properties: tuple[GroundedProperty, ...] = field(default_factory=tuple)
    relations: tuple[GroundedRelation, ...] = field(default_factory=tuple)
    events: tuple[GroundedEvent, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _nonempty("observation_id", self.observation_id))
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "properties", tuple(self.properties))
        object.__setattr__(self, "relations", tuple(self.relations))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))

        entity_ids = [entity.entity_id for entity in self.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity ids must be unique within a grounding frame")
        declared = set(entity_ids)

        missing: set[str] = set()
        for prop in self.properties:
            if prop.entity_id not in declared:
                missing.add(prop.entity_id)
        for relation in self.relations:
            if relation.subject_id not in declared:
                missing.add(relation.subject_id)
            if relation.object_id not in declared:
                missing.add(relation.object_id)
        for event in self.events:
            missing.update(participant for participant in event.participants if participant not in declared)
        if missing:
            raise ValueError(f"grounding claims reference undeclared entities: {sorted(missing)}")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": "tycho.grounding_frame",
            "schema_version": 1,
            "observation_id": self.observation_id,
            "entities": [item.to_dict() for item in self.entities],
            "properties": [item.to_dict() for item in self.properties],
            "relations": [item.to_dict() for item in self.relations],
            "events": [item.to_dict() for item in self.events],
            "notes": list(self.notes),
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize deterministically for durable evidence and regression tests."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            separators=None if indent is not None else (",", ":"),
            sort_keys=True,
        )


@runtime_checkable
class Grounder(Protocol):
    """Interface for future neural or deterministic grounding implementations."""

    def ground(self, *, observation_id: str, raw_observation: Any) -> GroundingFrame:
        """Convert one raw observation into a semantic grounding frame."""
        ...
