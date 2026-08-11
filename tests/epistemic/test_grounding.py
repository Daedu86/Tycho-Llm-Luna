from __future__ import annotations

import json

import pytest

from tycho.epistemic import (
    EvidenceRef,
    GroundedEntity,
    GroundedEvent,
    GroundedProperty,
    GroundedRelation,
    GroundingFrame,
)


def _sample_frame() -> GroundingFrame:
    frame = EvidenceRef(source="frame", level=0, turn=4)
    action = EvidenceRef(source="action", level=0, turn=4, note="ACTION_RIGHT")
    return GroundingFrame(
        observation_id="level-0-turn-4",
        entities=(
            GroundedEntity("E1", category="object", position=(6, 4), confidence=0.99, evidence=(frame,)),
            GroundedEntity("E2", category="object", position=(7, 4), confidence=0.91, evidence=(frame,)),
        ),
        properties=(
            GroundedProperty("E1", "color", "blue", confidence=1.0, evidence=(frame,)),
            GroundedProperty("E1", "movable", True, confidence=0.86, evidence=(frame, action)),
        ),
        relations=(
            GroundedRelation("E1", "left_of", "E2", confidence=0.98, evidence=(frame,)),
        ),
        events=(
            GroundedEvent(
                "move",
                participants=("E1",),
                attributes={"direction": "right", "delta": (1, 0)},
                confidence=0.94,
                evidence=(frame, action),
            ),
        ),
        notes=("Neural interpretation only; not yet symbolic truth.",),
    )


def test_grounding_frame_serializes_as_stable_semantic_contract() -> None:
    grounded = _sample_frame()
    payload = json.loads(grounded.to_json())

    assert payload["schema"] == "tycho.grounding_frame"
    assert payload["schema_version"] == 1
    assert payload["observation_id"] == "level-0-turn-4"
    assert payload["entities"][0]["position"] == [6, 4]
    assert payload["properties"][1]["confidence"] == 0.86
    assert payload["relations"][0] == {
        "confidence": 0.98,
        "evidence": [{"level": 0, "source": "frame", "turn": 4}],
        "object_id": "E2",
        "predicate": "left_of",
        "subject_id": "E1",
    }
    assert payload["events"][0]["attributes"]["delta"] == [1, 0]
    assert grounded.to_json() == grounded.to_json()


@pytest.mark.parametrize("confidence", [-0.01, 1.01, float("inf"), float("nan"), True])
def test_grounding_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        GroundedEntity("E1", confidence=confidence)


def test_grounding_rejects_duplicate_or_undeclared_entity_references() -> None:
    with pytest.raises(ValueError, match="unique"):
        GroundingFrame(
            observation_id="duplicate",
            entities=(GroundedEntity("E1"), GroundedEntity("E1")),
        )

    with pytest.raises(ValueError, match="undeclared"):
        GroundingFrame(
            observation_id="missing",
            entities=(GroundedEntity("E1"),),
            relations=(GroundedRelation("E1", "near", "E2"),),
        )


def test_grounding_rejects_opaque_values_and_normalizes_tuples() -> None:
    class Opaque:
        pass

    with pytest.raises(ValueError, match="JSON-serializable"):
        GroundedProperty("E1", "opaque", Opaque())  # type: ignore[arg-type]

    prop = GroundedProperty("E1", "bbox", (1, 2, 3, 4))  # type: ignore[arg-type]
    assert prop.value == [1, 2, 3, 4]


def test_grounding_keeps_extractor_confidence_without_collapsing_hypotheses() -> None:
    grounded = GroundingFrame(
        observation_id="ambiguous-green-object",
        entities=(GroundedEntity("G1", category="object"),),
        properties=(
            GroundedProperty("G1", "candidate_role", "goal", confidence=0.55),
            GroundedProperty("G1", "candidate_role", "key", confidence=0.32),
            GroundedProperty("G1", "candidate_role", "teleporter", confidence=0.13),
        ),
    )

    assert [claim.value for claim in grounded.properties] == ["goal", "key", "teleporter"]
    assert sum(claim.confidence for claim in grounded.properties) == pytest.approx(1.0)
