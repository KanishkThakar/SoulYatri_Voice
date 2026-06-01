"""JSON Schema documents and a dependency-free validator for planning models.

This module loads the JSON Schema documents authored under ``roadmap/schemas/``
(one per planning model) and provides a small, **dependency-free** validator that
enforces the subset of JSON Schema keywords the planning models need:

- ``type`` (including nullable unions expressed as a list, e.g. ``["string",
  "null"]``),
- ``required`` (every required field must be present),
- ``enum`` (used for the ``operator`` enum ``{<=, <, >=, >, ==}``, the gate
  ``kind``, the ``track`` label, and ``license_compat``),
- ``minimum`` / ``maximum`` (inclusive numeric bounds — used for the V/A/D bounds
  ``[-1.0, 1.0]`` and the ``confidence`` bound ``[0.0, 1.0]``),
- ``minLength`` (non-empty strings),
- ``minItems`` (e.g. ``guide_sections`` has at least one entry),
- ``items`` (array element subschema),
- ``properties`` / ``additionalProperties`` (object value subschemas),
- ``$ref`` to local ``#/$defs/...`` definitions.

The validator collects **every** violation rather than stopping at the first and
raises a structured :class:`SchemaValidationError` listing them all. It requires
no third-party ``jsonschema`` package, keeping the roadmap tooling dependency
light (the package stays pure-Python — Requirement 4.6).

Public API
----------
- :func:`validate` — validate a plain ``dict`` against a named schema.
- :class:`SchemaValidationError` — carries the structured violation list.
- :func:`validate_selection_weights` — assert the six ``SELECTION_WEIGHTS`` keys
  are exactly present (the selection-weight-keys constraint).
- :func:`schema_name_for` / :func:`schema_for` — map a planning dataclass or
  instance to its schema name (used by Task 28.3).
- :func:`available_schemas` / :func:`load_schema` — schema discovery/loading.

Validates portions of Requirements 1.4, 2.3, 6.1, and 9.1.
"""

from __future__ import annotations

import json
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any, Optional

from .models.selection import SELECTION_WEIGHTS

__all__ = [
    "SCHEMAS_DIR",
    "SchemaValidationError",
    "validate",
    "validate_selection_weights",
    "schema_name_for",
    "schema_for",
    "available_schemas",
    "load_schema",
]

#: Directory holding the per-model JSON Schema documents, resolved relative to
#: this module so loading works regardless of the current working directory.
SCHEMAS_DIR: Path = Path(__file__).resolve().parent / "schemas"

#: Cache of parsed schema documents keyed by schema name.
_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}

#: Mapping of planning dataclass *name* to its schema name. Keyed by class name
#: (rather than the class object) so this module need not import every model
#: module eagerly; the names are stable and match the dataclasses in
#: ``roadmap/models/`` and ``roadmap/roadmap_model.py``.
_CLASS_TO_SCHEMA: dict[str, str] = {
    "Phase": "phase",
    "Gate": "gate",
    "GateResult": "gate_result",
    "CandidateScores": "candidate_scores",
    "SelectionOutcome": "selection_outcome",
    "HarnessRun": "harness_run",
    "EmotionFeatures": "emotion_features",
    "ConsentRecord": "consent_record",
    "LicenseEntry": "license_entry",
    "NormalizationResult": "normalization_result",
    "Roadmap": "roadmap",
}

#: JSON Schema type name -> the Python types that satisfy it. ``bool`` is a
#: subclass of ``int`` in Python, so ``number``/``integer`` deliberately exclude
#: ``bool`` (handled explicitly in :func:`_type_matches`).
_JSON_TYPE_TO_PY: dict[str, tuple] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "null": (type(None),),
}


class SchemaValidationError(Exception):
    """Raised when an object fails schema validation.

    Carries the **complete** list of violations (not just the first), so callers
    and tests can inspect every problem at once.

    Attributes:
        schema_name: The name of the schema the object was validated against.
        errors: A list of human-readable violation messages, each prefixed with
            the JSON-pointer-style location of the offending value.
    """

    def __init__(self, schema_name: str, errors: list[str]) -> None:
        self.schema_name = schema_name
        self.errors = list(errors)
        count = len(self.errors)
        joined = "; ".join(self.errors)
        super().__init__(
            f"{count} schema violation(s) for schema {schema_name!r}: {joined}"
        )


# ---------------------------------------------------------------------------
# Schema loading / discovery
# ---------------------------------------------------------------------------
def available_schemas() -> list[str]:
    """Return the sorted names of every schema document under ``schemas/``."""
    return sorted(p.stem for p in SCHEMAS_DIR.glob("*.json"))


def load_schema(schema_name: str) -> dict[str, Any]:
    """Load and cache the parsed JSON Schema document named ``schema_name``.

    Args:
        schema_name: The schema's file stem, e.g. ``"phase"`` or
            ``"gate_result"``.

    Returns:
        The parsed schema document as a plain ``dict``.

    Raises:
        KeyError: If no schema file with that name exists under ``schemas/``.
    """
    cached = _SCHEMA_CACHE.get(schema_name)
    if cached is not None:
        return cached

    path = SCHEMAS_DIR / f"{schema_name}.json"
    if not path.exists():
        raise KeyError(
            f"unknown schema {schema_name!r}; available: {available_schemas()}"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    _SCHEMA_CACHE[schema_name] = document
    return document


# ---------------------------------------------------------------------------
# Schema-name mapping
# ---------------------------------------------------------------------------
def schema_name_for(cls_or_name: Any) -> str:
    """Return the schema name for a planning dataclass, instance, or class name.

    Accepts a dataclass type, a dataclass instance, or a plain class-name
    string and returns the corresponding schema name (e.g. ``EmotionFeatures``
    -> ``"emotion_features"``).

    Raises:
        KeyError: If there is no schema mapped for the given class.
    """
    if isinstance(cls_or_name, str):
        name = cls_or_name
    elif isinstance(cls_or_name, type):
        name = cls_or_name.__name__
    else:
        name = type(cls_or_name).__name__

    try:
        return _CLASS_TO_SCHEMA[name]
    except KeyError as exc:
        raise KeyError(f"no schema mapped for {name!r}") from exc


def schema_for(obj: Any) -> str:
    """Return the schema name for a planning dataclass instance (or class).

    Thin alias over :func:`schema_name_for` kept for call-site readability where
    an *instance* is passed (used by the Task 28.3 property test).
    """
    return schema_name_for(obj)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate(obj_dict: dict, schema_name: str) -> None:
    """Validate ``obj_dict`` against the named schema.

    Collects **every** violation and raises a structured
    :class:`SchemaValidationError` listing them all when the object is invalid;
    returns ``None`` (passes silently) when the object is valid.

    Enforced constraints include required fields, the ``operator`` enum
    ``{<=, <, >=, >, ==}``, the V/A/D bounds ``[-1.0, 1.0]`` (and the
    ``confidence`` bound ``[0.0, 1.0]``) declared in ``emotion_features.json``,
    string/array non-emptiness, and nested object/array shapes.

    Args:
        obj_dict: The plain dict to validate (e.g. the output of
            ``serialization.to_dict(x)``).
        schema_name: The schema to validate against (see
            :func:`available_schemas`).

    Raises:
        KeyError: If ``schema_name`` is unknown.
        SchemaValidationError: If ``obj_dict`` violates the schema.
    """
    schema = load_schema(schema_name)
    errors: list[str] = []
    _validate_node(obj_dict, schema, schema, "$", errors)
    if errors:
        raise SchemaValidationError(schema_name, errors)


def validate_selection_weights(weights: dict) -> None:
    """Assert that ``weights`` has exactly the six ``SELECTION_WEIGHTS`` keys.

    This encodes the selection-weight-keys constraint: a selection-weight map is
    valid only when its key set is exactly the six canonical criteria
    (``streaming_latency``, ``hinglish_capability``, ``full_duplex``,
    ``license_permissiveness``, ``vram_footprint``, ``community_activity``).

    Raises:
        SchemaValidationError: If keys are missing or unexpected. The error's
            ``errors`` list names every missing and every unexpected key.
    """
    errors: list[str] = []
    if not isinstance(weights, dict):
        raise SchemaValidationError(
            "selection_weights",
            [f"$: expected an object of selection weights, got {_typename(weights)}"],
        )

    expected = set(SELECTION_WEIGHTS)
    present = set(weights)
    for missing in sorted(expected - present):
        errors.append(f"$: missing required selection-weight key {missing!r}")
    for extra in sorted(present - expected):
        errors.append(f"$: unexpected selection-weight key {extra!r}")
    if errors:
        raise SchemaValidationError("selection_weights", errors)


# ---------------------------------------------------------------------------
# Internal recursive validator
# ---------------------------------------------------------------------------
def _validate_node(
    value: Any,
    subschema: dict[str, Any],
    root: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    """Validate ``value`` against ``subschema``, appending violations to ``errors``."""
    # Resolve local $ref against the root schema first.
    if "$ref" in subschema:
        resolved = _resolve_ref(subschema["$ref"], root)
        if resolved is None:
            errors.append(f"{path}: cannot resolve $ref {subschema['$ref']!r}")
            return
        _validate_node(value, resolved, root, path, errors)
        return

    # type
    expected_type = subschema.get("type")
    if expected_type is not None and not _type_matches(value, expected_type):
        errors.append(
            f"{path}: expected type {expected_type!r}, got {_typename(value)}"
        )
        # If the fundamental type is wrong, deeper checks are not meaningful.
        return

    # enum
    if "enum" in subschema:
        allowed = subschema["enum"]
        if value not in allowed:
            errors.append(f"{path}: value {value!r} is not one of {allowed!r}")

    # numeric bounds (skip bools, which are not real numbers here)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in subschema and value < subschema["minimum"]:
            errors.append(
                f"{path}: value {value!r} is below minimum {subschema['minimum']!r}"
            )
        if "maximum" in subschema and value > subschema["maximum"]:
            errors.append(
                f"{path}: value {value!r} is above maximum {subschema['maximum']!r}"
            )

    # string length
    if isinstance(value, str) and "minLength" in subschema:
        if len(value) < subschema["minLength"]:
            errors.append(
                f"{path}: string length {len(value)} is below minLength "
                f"{subschema['minLength']}"
            )

    # arrays
    if isinstance(value, list):
        if "minItems" in subschema and len(value) < subschema["minItems"]:
            errors.append(
                f"{path}: array length {len(value)} is below minItems "
                f"{subschema['minItems']}"
            )
        item_schema = subschema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_node(
                    item, item_schema, root, f"{path}[{index}]", errors
                )

    # objects
    if isinstance(value, dict):
        for required_key in subschema.get("required", []):
            if required_key not in value:
                errors.append(f"{path}: missing required field {required_key!r}")

        properties = subschema.get("properties", {})
        for key, prop_schema in properties.items():
            if key in value:
                _validate_node(
                    value[key], prop_schema, root, f"{path}.{key}", errors
                )

        additional = subschema.get("additionalProperties")
        if isinstance(additional, dict):
            for key, item in value.items():
                if key in properties:
                    continue
                _validate_node(item, additional, root, f"{path}.{key}", errors)


def _resolve_ref(ref: str, root: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Resolve a local ``#/...`` JSON-pointer ``$ref`` against ``root``."""
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            return None
        node = node[token]
    return node if isinstance(node, dict) else None


def _type_matches(value: Any, expected_type: Any) -> bool:
    """Return whether ``value`` matches a JSON Schema ``type`` declaration.

    ``expected_type`` may be a single type name or a list of names (a nullable
    union such as ``["string", "null"]``). ``bool`` never satisfies ``number``
    or ``integer``.
    """
    names = expected_type if isinstance(expected_type, list) else [expected_type]
    for name in names:
        py_types = _JSON_TYPE_TO_PY.get(name)
        if py_types is None:
            continue
        if name in ("number", "integer") and isinstance(value, bool):
            # bool is a subclass of int; reject it as a number/integer.
            continue
        if isinstance(value, py_types):
            return True
    return False


def _typename(value: Any) -> str:
    """Return a friendly type name for error messages."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__
