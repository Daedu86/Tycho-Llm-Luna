from __future__ import annotations

import pytest

from tycho.epistemic.grid_grounder import GridComponentGrounder, summarize_grounding_frame


def _properties(frame):
    out = {}
    for prop in frame.properties:
        out.setdefault(prop.entity_id, {})[prop.name] = prop.value
    return out


def test_component_grounding_is_deterministic_and_geometric() -> None:
    frame = GridComponentGrounder().ground(
        observation_id="g:L0:T0",
        raw_observation={
            "grid": [
                [0, 1, 0, 2],
                [0, 1, 0, 2],
                [0, 0, 0, 0],
                [3, 0, 3, 3],
            ],
            "source": "level_0/turn_000.txt",
            "level": 0,
            "turn": 0,
        },
    )

    props = _properties(frame)
    assert [props[e.entity_id]["color"] for e in frame.entities] == [1, 2, 3, 3]
    assert [props[e.entity_id]["area"] for e in frame.entities] == [2, 2, 1, 2]
    assert props["component-000"]["bbox"] == [0, 1, 1, 1]
    assert props["component-003"]["bbox"] == [3, 2, 3, 3]
    assert frame.entities[0].position == (0, 1)
    assert frame.notes[1] == "background_color=0"
    assert frame.to_json() == frame.to_json()


def test_background_ties_choose_lower_color_id() -> None:
    frame = GridComponentGrounder().ground(
        observation_id="tie",
        raw_observation=[[2, 1], [1, 2]],
    )
    assert "background_color=1" in frame.notes
    assert len(frame.entities) == 2


def test_roles_and_cross_turn_identity_are_not_inferred() -> None:
    frame = GridComponentGrounder().ground(
        observation_id="roles",
        raw_observation=[[0, 4], [0, 4]],
    )
    assert all(entity.category == "grid_component" for entity in frame.entities)
    assert "roles_not_inferred=true" in frame.notes
    assert "entity_identity_scope=observation_local" in frame.notes


def test_grounder_rejects_non_rectangular_grid() -> None:
    with pytest.raises(ValueError, match="rectangular"):
        GridComponentGrounder().ground(observation_id="bad", raw_observation=[[0, 1], [0]])


def test_summary_is_bounded_and_points_to_sidecar_detail() -> None:
    frame = GridComponentGrounder().ground(
        observation_id="summary",
        raw_observation=[[0, 1, 0, 2, 0, 3]],
    )
    text = summarize_grounding_frame(frame, max_entities=2)
    assert "component-000" in text
    assert "component-001" in text
    assert "component-002" not in text
    assert "1 additional components" in text
