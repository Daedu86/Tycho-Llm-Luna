"""Deterministic low-level grounding for ARC grid observations.

This module is the first live L1 grounder. It deliberately stops at perceptual
structure: connected same-color components, their geometry, and provenance. It
does not assign task roles such as player, key, wall, enemy, or goal. Those
interpretations remain neural hypotheses for the later belief layer.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Any

from .grounding import EvidenceRef, GroundedEntity, GroundedProperty, GroundingFrame


def _normalized_grid(raw: Any) -> list[list[int]]:
    rows = [list(row) for row in raw]
    if not rows or not rows[0]:
        raise ValueError("grid must be non-empty")
    width = len(rows[0])
    out: list[list[int]] = []
    for r, row in enumerate(rows):
        if len(row) != width:
            raise ValueError("grid must be rectangular")
        normalized = []
        for c, value in enumerate(row):
            if isinstance(value, bool) or not isinstance(value, int):
                try:
                    converted = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"grid[{r}][{c}] must be an integer") from exc
                if converted != value:
                    raise ValueError(f"grid[{r}][{c}] must be an integer")
                value = converted
            normalized.append(int(value))
        out.append(normalized)
    return out


def _background_color(grid: list[list[int]]) -> int:
    counts = Counter(cell for row in grid for cell in row)
    # Most frequent color is the deterministic perceptual background baseline.
    # Ties choose the lower color id so serialization is stable.
    return min(counts, key=lambda color: (-counts[color], color))


def _components(grid: list[list[int]], background: int) -> list[tuple[int, list[tuple[int, int]]]]:
    height, width = len(grid), len(grid[0])
    seen: set[tuple[int, int]] = set()
    found: list[tuple[int, list[tuple[int, int]]]] = []
    for row in range(height):
        for col in range(width):
            color = grid[row][col]
            if color == background or (row, col) in seen:
                continue
            queue = deque([(row, col)])
            seen.add((row, col))
            cells: list[tuple[int, int]] = []
            while queue:
                rr, cc = queue.popleft()
                cells.append((rr, cc))
                for nr, nc in ((rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1)):
                    if not (0 <= nr < height and 0 <= nc < width):
                        continue
                    if (nr, nc) in seen or grid[nr][nc] != color:
                        continue
                    seen.add((nr, nc))
                    queue.append((nr, nc))
            cells.sort()
            found.append((color, cells))
    found.sort(key=lambda item: (item[0], item[1][0][0], item[1][0][1], len(item[1])))
    return found


class GridComponentGrounder:
    """Ground exact grid structure into observation-local component entities.

    Entity ids are intentionally local to one ``GroundingFrame``. L2 is responsible
    for deciding whether entities in different observations refer to the same object.
    """

    def ground(self, *, observation_id: str, raw_observation: Any) -> GroundingFrame:
        if isinstance(raw_observation, dict) and "grid" in raw_observation:
            grid_raw = raw_observation["grid"]
            source = str(raw_observation.get("source") or observation_id)
            level = raw_observation.get("level")
            turn = raw_observation.get("turn")
            note = str(raw_observation.get("note") or "exact grid component grounding")
        else:
            grid_raw = raw_observation
            source = observation_id
            level = turn = None
            note = "exact grid component grounding"

        grid = _normalized_grid(grid_raw)
        background = _background_color(grid)
        evidence = (EvidenceRef(source=source, level=level, turn=turn, note=note),)
        entities = []
        properties = []
        for index, (color, cells) in enumerate(_components(grid, background)):
            rows = [row for row, _ in cells]
            cols = [col for _, col in cells]
            r0, r1, c0, c1 = min(rows), max(rows), min(cols), max(cols)
            entity_id = f"component-{index:03d}"
            entities.append(GroundedEntity(
                entity_id=entity_id,
                category="grid_component",
                position=(r0, c0),
                confidence=1.0,
                evidence=evidence,
            ))
            for name, value in (
                ("color", color),
                ("area", len(cells)),
                ("bbox", [r0, c0, r1, c1]),
                ("height", r1 - r0 + 1),
                ("width", c1 - c0 + 1),
            ):
                properties.append(GroundedProperty(
                    entity_id=entity_id,
                    name=name,
                    value=value,
                    confidence=1.0,
                    evidence=evidence,
                ))

        return GroundingFrame(
            observation_id=observation_id,
            entities=tuple(entities),
            properties=tuple(properties),
            notes=(
                f"grid_shape={len(grid)}x{len(grid[0])}",
                f"background_color={background}",
                "entity_identity_scope=observation_local",
                "roles_not_inferred=true",
            ),
        )


def summarize_grounding_frame(frame: GroundingFrame, *, max_entities: int = 12) -> str:
    """Compact model-facing summary; the JSON sidecar remains the authoritative record."""
    props: dict[str, dict[str, Any]] = {}
    for prop in frame.properties:
        props.setdefault(prop.entity_id, {})[prop.name] = prop.value
    lines = [
        f"observation={frame.observation_id}; components={len(frame.entities)}; "
        + "; ".join(frame.notes[:2]),
        "Component ids are observation-local proposals, not persistent object identities.",
    ]
    for entity in frame.entities[:max_entities]:
        p = props.get(entity.entity_id, {})
        lines.append(
            f"- {entity.entity_id}: color={p.get('color')}, area={p.get('area')}, "
            f"bbox={p.get('bbox')}, anchor(row,col)={list(entity.position) if entity.position else None}"
        )
    omitted = len(frame.entities) - max_entities
    if omitted > 0:
        lines.append(f"- ... {omitted} additional components in the sidecar")
    return "\n".join(lines)
