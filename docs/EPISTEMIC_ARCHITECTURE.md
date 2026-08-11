# Epistemic Neuro-Symbolic Architecture

This branch evolves Tycho's reasoning architecture while keeping the Luna/Codex transport isolated as
a transport concern.

## Experimental ladder

| Level | Capability | Scope |
|---|---|---|
| L0 | Tycho + Luna baseline | Existing Tycho observation and control loop |
| L1 | Semantic grounding | Adds a structured observation channel; control algorithm is unchanged |
| L2 | Persistent belief state | Later |
| L3 | Competing causal world models | Later |
| L4 | Epistemic verification / belief update | Later |
| L5 | Goal progress + information-gain planning | Later |
| L6 | Meta-controller | Later |

Keeping each level isolated makes benchmark deltas attributable.

## L1: semantic grounding

The `tycho.epistemic` package is the boundary between raw/neural perception and symbolic world-model
code:

```text
raw frame / action evidence
          |
          v
  perceptual grounding
          |
          v
+---------------------------+
| L1 semantic grounding     |
| entity proposals          |
| properties                |
| relations                 |
| events                    |
| confidence + provenance   |
+-------------+-------------+
              |
              v
 neural interpretation / actor
              |
              v
existing symbolic builder / world model
```

L1 deliberately does **not** declare grounded observations to be symbolic truth. The first live
grounder is deterministic and conservative: it identifies 4-connected same-color components and
records geometry, but does not infer roles such as player, wall, key, enemy, or goal. Those semantic
roles remain hypotheses for neural reasoning and, later, L2 belief updates.

### Grounding contract

A `GroundingFrame` has a stable schema (`tycho.grounding_frame`, version 1) and contains:

- `GroundedEntity`: identity proposal, optional category and grid position.
- `GroundedProperty`: proposed property/value for an entity.
- `GroundedRelation`: proposed relation between two declared entities.
- `GroundedEvent`: event plus participants and JSON-safe attributes.
- `EvidenceRef`: provenance pointer such as frame/action, level, turn, and an optional note.

Every claim may carry confidence in `[0, 1]` and one or more evidence references. Frames reject
duplicate identities, references to undeclared entities, non-finite confidence, and opaque
non-JSON values. Serialization is deterministic so future belief artifacts and regressions can
compare grounding records reliably.

## Live L1 approach

`tycho.epistemic.grounded_agent` subclasses the existing Tycho actor rather than replacing it. On
each decision frame it:

1. lets the normal Tycho workspace record the exact grid;
2. segments the current grid into observation-local connected components;
3. writes `level_<L>/scene_<TTT>.json` using the `tycho.grounding_frame` schema;
4. appends a bounded grounding summary to the same actor turn;
5. leaves the world-model policy, verifier, planner, tool loop, and Luna transport unchanged.

Tycho already archives `scene_*.json` with the rest of an attempt, so grounding evidence follows the
same reset/attempt provenance as the exact frame that produced it.

Run the L0 baseline exactly as before:

```bash
python -m tycho.harness.run_parallel --approach tycho ...
```

Run the L1 grounded approach through the existing dotted-module approach loader:

```bash
python -m tycho.harness.run_parallel --approach tycho.epistemic.grounded_agent ...
```

This creates a clean A/B comparison: same model, transport, Tycho control algorithm, and benchmark;
the independent variable is the structured grounding observation channel.

### Identity boundary

L1 entity ids are **observation-local**. `component-003` at turn 7 is not assumed to be the same
object as `component-003` at turn 8. Temporal identity resolution is deliberately deferred to L2,
where evidence can support or weaken persistent object hypotheses instead of hard-coding identity
from color or position.

## Non-goals of L1

L1 does not yet:

- persist beliefs across turns;
- normalize competing claims into posterior probabilities;
- create or rank multiple `world_model.py` hypotheses;
- update confidence after verification;
- choose actions explicitly for information gain;
- decide when neural versus symbolic reasoning should run.

Those behaviors belong to L2-L6. The next milestone is **L2 BeliefState**, consuming the durable
`scene_*.json` stream and resolving cross-turn identity and competing semantic hypotheses.
