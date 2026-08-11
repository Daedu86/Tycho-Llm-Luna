"""L1 Tycho approach: base Tycho plus a live semantic grounding channel.

The control loop, world-model policy, verifier, planner, and Luna transport are
unchanged. The only intervention is an additional deterministic observation
representation written next to each recorded frame and summarized in that turn's
user message.
"""

from __future__ import annotations

from tycho.agent.agent import TychoAgent
from tycho.harness.agent import Agent

from .grid_grounder import GridComponentGrounder, summarize_grounding_frame


class GroundedTychoAgent(TychoAgent):
    """Tycho with L1 grounded component evidence exposed to the actor."""

    name = "tycho_grounded_l1"

    def __init__(self, tools=None):
        super().__init__(tools=tools)
        self._l1_grounder = GridComponentGrounder()
        self._l1_grounding_frame = None
        self._l1_grounding_path = None

    def _frame_message(self, grid, state, avail, frame_boundary: str | None) -> str:
        base = super()._frame_message(grid, state, avail, frame_boundary)
        observation_id = f"{self.ws.dir.name}:level-{self.level}:turn-{self.turn_in_level}"
        path = f"level_{self.level}/scene_{self.turn_in_level:03d}.json"
        source = f"level_{self.level}/turn_{self.turn_in_level:03d}.txt"
        frame = self._l1_grounder.ground(
            observation_id=observation_id,
            raw_observation={
                "grid": grid,
                "source": source,
                "level": self.level,
                "turn": self.turn_in_level,
                "note": "deterministic 4-connected same-color component grounding",
            },
        )
        self.ws.write_file(path, frame.to_json(indent=2) + "\n")
        self._l1_grounding_frame = frame
        self._l1_grounding_path = path
        summary = summarize_grounding_frame(frame)
        return (
            base
            + "\n\n=== L1 semantic grounding (structured observation, not symbolic truth) ===\n"
            + summary
            + f"\nFull grounding artifact: {path}\n"
            + "Do not assume component roles or cross-turn identity from this grounding alone."
        )

    def choose_action(self, frames, latest_frame, available_actions):
        self._l1_grounding_frame = None
        self._l1_grounding_path = None
        choice = super().choose_action(frames, latest_frame, available_actions)
        frame = self._l1_grounding_frame
        if frame is not None:
            choice.reasoning = {
                **(choice.reasoning or {}),
                "grounding": {
                    "schema": "tycho.grounding_frame",
                    "schema_version": 1,
                    "path": self._l1_grounding_path,
                    "observation_id": frame.observation_id,
                    "entity_count": len(frame.entities),
                    "property_count": len(frame.properties),
                },
            }
        return choice


def build_agent() -> Agent:
    return GroundedTychoAgent()
