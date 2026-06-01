# `roadmap.emotion_persona`

Public API of the `roadmap.emotion_persona` component. Generated from live signatures and docstrings.

## class `EmotionPersonaController`

```python
EmotionPersonaController(*, distress_labels: 'FrozenSet[str]' = frozenset({'fear', 'sad', 'angry'}), distress_confidence_threshold: 'float' = 0.5) -> 'None'
```

Selects a persona-conditioning mode from per-turn emotion features.

The controller is stateless; a single instance can be reused across turns.
The distress label set and confidence threshold are configurable for
testing/tuning but default to the design's values.

### Methods

#### `select_conditioning`

```python
select_conditioning(self, features: 'EmotionFeatures') -> 'ConditioningMode'
```

Return the :data:`ConditioningMode` to apply for this turn.

This is the core decision output (Requirements 6.3, 6.5, 6.7). The turn
always continues regardless of the outcome; failed/unavailable
extraction simply yields ``NEUTRAL`` rather than interrupting the turn.

#### `select`

```python
select(self, features: 'EmotionFeatures') -> 'ConditioningSelection'
```

Return the full :class:`ConditioningSelection` for this turn.

Exposes the effective, clamped conditioning V/A/D and discrete tag
alongside the mode (Requirement 6.1 — never emit out-of-range values).


## class `ConditioningSelection`

```python
ConditioningSelection(mode: 'ConditioningMode', valence: 'float', arousal: 'float', dominance: 'float', tag: 'str') -> None
```

The full result of a conditioning decision.

``mode`` is the core output (see :data:`ConditioningMode`). The
``valence`` / ``arousal`` / ``dominance`` fields carry the *effective*
conditioning vector that should be injected for the turn — always clamped to
``[-1.0, 1.0]`` — and ``tag`` is the dominant discrete label applied.

For ``NEUTRAL`` the vector is ``(0.0, 0.0, 0.0)`` with the ``"neutral"`` tag.
