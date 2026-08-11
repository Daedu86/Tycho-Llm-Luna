# Epistemic Neuro-Symbolic Architecture

This branch evolves Tycho's reasoning architecture while keeping the Luna/Codex transport isolated as
a transport concern.

## Experimental ladder

| Level | Capability | Changes action policy? |
|---|---|---|
| L0 | Tycho + Luna baseline | No architecture change |
| L1 | Semantic grounding | **No** |
| L2 | Persistent belief state | Later |
| L3 | Competing causal world models | Later |
| L4 | Epistemic verification / belief update | Later |
| L5 | Goal progress + information-gain planning | Later |
| L6 | Meta-controller | Later |

The branch starts at **L1 only**. Keeping each level isolated makes benchmark deltas attributable.

## L1: semantic grounding

The new `tycho.epistemic` package is the boundary between neural interpretation and symbolic
world-model code:

```text
raw frame / action evidence
          |
          v
    neural interpretation
          |
          v
+---------------------------+
| L1 semantic grounding     |
| entity identity proposals |
| properties                |
| relations                 |
| events                    |
| confidence + provenance   |
+-------------+-------------+
              |
              v
existing Tycho actor / builder / world model
```

L1 deliberately does **not** declare grounded observations to be true. A neural system may record,
for example, three candidate roles for one green object with different confidence values. Those are
observation-level claims. L2 will later decide how evidence changes persistent beliefs.

### Grounding contract

A `GroundingFrame` has a stable schema (`tycho.grounding_frame`, version 1) and contains:

- `GroundedEntity`: stable identity proposal, optional category and grid position.
- `GroundedProperty`: proposed property/value for an entity.
- `GroundedRelation`: proposed relation between two declared entities.
- `GroundedEvent`: event plus participants and JSON-safe attributes.
- `EvidenceRef`: provenance pointer such as frame/action, level, turn, and an optional note.

Every claim may carry confidence in `[0, 1]` and one or more evidence references. Frames reject
duplicate identities, references to undeclared entities, non-finite confidence, and opaque
non-JSON values. Serialization is deterministic so future belief artifacts and regressions can
compare grounding records reliably.

## Non-goals of L1

L1 does not yet:

- persist beliefs across turns;
- normalize competing claims into posterior probabilities;
- create or rank multiple `world_model.py` hypotheses;
- update confidence after verification;
- choose actions for information gain;
- decide when neural versus symbolic reasoning should run.

Those behaviors belong to L2-L6. This boundary is intentional: the first benchmark after wiring a
grounder should measure the effect of structured semantic grounding without simultaneously changing
planning or falsification policy.
