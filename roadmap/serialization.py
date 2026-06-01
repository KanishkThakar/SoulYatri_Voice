"""Serialization codecs for the roadmap's planning dataclasses.

This module provides a small, generic, dependency-light serialization layer for
every planning dataclass in the ``roadmap`` package and the :class:`Roadmap`
aggregate. It converts those structures to and from plain, JSON/YAML-compatible
Python values (``dict``/``list``/``str``/``int``/``float``/``bool``/``None``)
and offers stdlib-``json`` and ``pyyaml`` string codecs on top.

Design goals
------------
- **Generic dispatch.** Rather than hand-writing a converter per dataclass, the
  codecs introspect each dataclass with :func:`dataclasses.fields` and
  :func:`typing.get_type_hints` and recurse generically into ``list[...]``,
  ``dict[..., ...]``, ``Optional[...]``, ``Literal[...]``, and nested
  dataclasses. Adding a field (or a whole new dataclass) needs no change here.
- **Lossless round-trip.** For every planning dataclass ``x`` the invariant
  ``from_dict(cls, to_dict(x)) == x`` holds, and likewise for the JSON and YAML
  string codecs. ``Literal`` / enum values are stored as their plain string
  value, and floats are preserved as Python floats (stdlib ``json`` and
  ``yaml.safe_*`` both round-trip float ``repr`` without precision loss — floats
  are never stringified).
- **Strict reconstruction.** :func:`from_dict` rejects unknown keys with a
  :class:`SerializationError` so a typo'd or stale payload fails loudly instead
  of silently dropping data.

The module is pure Python and imports no GPU/model-training framework, so it
preserves the package's import-only / no-training guarantee (Requirement 4.6).

Validates portions of Requirements 1.1, 1.4, and 12.7.
"""

from __future__ import annotations

import json
import types
from dataclasses import fields, is_dataclass
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import yaml

__all__ = [
    "SerializationError",
    "to_dict",
    "from_dict",
    "dumps_json",
    "loads_json",
    "dumps_yaml",
    "loads_yaml",
]

#: Cache of resolved type hints per dataclass type. ``typing.get_type_hints``
#: re-evaluates stringized annotations (the modules use
#: ``from __future__ import annotations``) on every call, so memoizing keeps
#: reconstruction cheap across large/nested payloads.
_HINT_CACHE: dict[type, dict[str, Any]] = {}

#: The Python value types that are already JSON/YAML primitives and are emitted
#: (and accepted) verbatim by the codecs.
_PRIMITIVES = (str, int, float, bool, type(None))


class SerializationError(ValueError):
    """Raised when a payload cannot be reconstructed into the target dataclass.

    Subclasses :class:`ValueError` so callers may catch either. It is raised for
    a non-mapping payload where a dataclass is expected and for unknown keys
    that do not correspond to any field of the target dataclass.
    """


def _type_hints(cls: type) -> dict[str, Any]:
    """Return (and cache) the resolved type hints for dataclass ``cls``."""
    hints = _HINT_CACHE.get(cls)
    if hints is None:
        hints = get_type_hints(cls)
        _HINT_CACHE[cls] = hints
    return hints


# ---------------------------------------------------------------------------
# Encoding: dataclass -> plain JSON/YAML-compatible value
# ---------------------------------------------------------------------------
def to_dict(obj: Any) -> Any:
    """Convert ``obj`` to a plain, JSON/YAML-compatible value.

    A dataclass instance becomes a ``dict`` keyed by field name with each value
    converted recursively; lists/tuples become lists; dicts are copied with
    their values converted recursively; ``Literal`` / enum values are stored as
    their plain (string) value; and JSON primitives (``str``/``int``/``float``/
    ``bool``/``None``) pass through unchanged. Floats are emitted as Python
    floats — never stringified — so the JSON/YAML codecs round-trip them without
    precision loss.

    The top-level call on any planning dataclass returns a ``dict``; the return
    type is widened to ``Any`` because the function recurses through lists and
    primitive values as well.

    Args:
        obj: A planning dataclass instance (or any nested value reachable from
            one): a dataclass, list, tuple, dict, or JSON primitive.

    Returns:
        A structure composed solely of ``dict``/``list``/``str``/``int``/
        ``float``/``bool``/``None`` that mirrors ``obj``.
    """
    # ``is_dataclass`` is also true for dataclass *types*; we only convert
    # instances, so exclude the class objects themselves.
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_dict(value) for key, value in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Decoding: plain value -> dataclass instance
# ---------------------------------------------------------------------------
def from_dict(cls: type, data: Any) -> Any:
    """Reconstruct an instance of dataclass ``cls`` from ``data``.

    Inverse of :func:`to_dict`: for every planning dataclass ``x`` the invariant
    ``from_dict(cls, to_dict(x)) == x`` holds. Each field is reconstructed
    according to ``cls``'s resolved type hints, recursing into nested
    dataclasses, ``list[...]`` element types, ``dict[..., V]`` value types, and
    unwrapping ``Optional[...]`` (``None`` stays ``None``). ``Literal[...]``
    values and untyped/bare containers are taken verbatim.

    Fields absent from ``data`` fall back to the dataclass's own defaults (so
    payloads produced before a defaulted field was added still load). Unknown
    keys are rejected.

    Args:
        cls: The target dataclass type.
        data: A mapping produced by :func:`to_dict` (or an equivalent decoded
            JSON/YAML object).

    Returns:
        A new ``cls`` instance.

    Raises:
        SerializationError: If ``cls`` is a dataclass but ``data`` is not a
            mapping, or if ``data`` contains a key that is not a field of
            ``cls``.
    """
    if not (is_dataclass(cls) and isinstance(cls, type)):
        # Not a dataclass target: nothing to reconstruct, return as-is.
        return data
    if not isinstance(data, dict):
        raise SerializationError(
            f"expected a mapping to build {cls.__name__}, got {type(data).__name__}"
        )

    field_map = {f.name: f for f in fields(cls)}
    unknown = [key for key in data if key not in field_map]
    if unknown:
        raise SerializationError(
            f"unknown field(s) {sorted(unknown)!r} for {cls.__name__}; "
            f"known fields are {sorted(field_map)!r}"
        )

    hints = _type_hints(cls)
    kwargs: dict[str, Any] = {}
    for name in field_map:
        if name in data:
            kwargs[name] = _from_value(hints.get(name, Any), data[name])
    return cls(**kwargs)


def _from_value(annotation: Any, value: Any) -> Any:
    """Reconstruct ``value`` according to its declared ``annotation``.

    Handles the typing constructs used across the planning dataclasses:
    ``Optional``/``Union`` (``None`` passes through, otherwise the sole non-None
    arm is used), ``Literal`` (verbatim), ``list[...]`` and ``dict[..., V]``
    (recurse into element/value types, dict keys are JSON strings and kept
    as-is), nested dataclasses (delegate to :func:`from_dict`), and primitives /
    bare containers (verbatim).
    """
    if value is None:
        return None

    origin = get_origin(annotation)

    # Optional[...] / Union[...]: unwrap to the single non-None arm.
    if origin is Union or origin is types.UnionType:
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return _from_value(non_none[0], value)
        # Ambiguous union (not used by the planning models): keep verbatim.
        return value

    # Literal[...] values are stored as their plain value.
    if origin is Literal:
        return value

    # list[...] : reconstruct each element by the declared element type.
    if origin is list:
        args = get_args(annotation)
        elem_type = args[0] if args else Any
        return [_from_value(elem_type, item) for item in value]

    # dict[K, V] : keys are JSON strings (kept as-is); recurse into values.
    if origin is dict:
        args = get_args(annotation)
        if len(args) == 2:
            value_type = args[1]
            return {key: _from_value(value_type, val) for key, val in value.items()}
        return dict(value)

    # Nested dataclass.
    if is_dataclass(annotation) and isinstance(annotation, type):
        return from_dict(annotation, value)

    # Primitives, ``Any``, and bare/untyped containers (e.g. ``hardware: dict``).
    return value


# ---------------------------------------------------------------------------
# JSON string codecs (stdlib json)
# ---------------------------------------------------------------------------
def dumps_json(obj: Any, *, indent: int | None = None) -> str:
    """Serialize a planning dataclass ``obj`` to a JSON string.

    Delegates to :func:`to_dict` then :func:`json.dumps`. ``ensure_ascii`` is
    disabled so non-ASCII text (e.g. Devanagari) is preserved literally rather
    than escaped. Floats keep full precision via stdlib ``json``'s ``repr``.

    Args:
        obj: The planning dataclass instance to serialize.
        indent: Optional pretty-print indent passed through to ``json.dumps``.

    Returns:
        The JSON text.
    """
    return json.dumps(to_dict(obj), ensure_ascii=False, indent=indent)


def loads_json(cls: type, text: str) -> Any:
    """Parse JSON ``text`` and reconstruct an instance of dataclass ``cls``.

    Inverse of :func:`dumps_json`: ``loads_json(cls, dumps_json(x)) == x`` for
    every planning dataclass ``x``.
    """
    return from_dict(cls, json.loads(text))


# ---------------------------------------------------------------------------
# YAML string codecs (pyyaml, safe loader/dumper)
# ---------------------------------------------------------------------------
def dumps_yaml(obj: Any) -> str:
    """Serialize a planning dataclass ``obj`` to a YAML string.

    Delegates to :func:`to_dict` then :func:`yaml.safe_dump`. ``sort_keys`` is
    disabled to preserve field declaration order and ``allow_unicode`` is
    enabled so non-ASCII text is preserved literally. The safe dumper only emits
    plain scalars and containers, matching the JSON-compatible shape produced by
    :func:`to_dict`.

    Args:
        obj: The planning dataclass instance to serialize.

    Returns:
        The YAML text.
    """
    return yaml.safe_dump(to_dict(obj), sort_keys=False, allow_unicode=True)


def loads_yaml(cls: type, text: str) -> Any:
    """Parse YAML ``text`` and reconstruct an instance of dataclass ``cls``.

    Inverse of :func:`dumps_yaml`: ``loads_yaml(cls, dumps_yaml(x)) == x`` for
    every planning dataclass ``x``. Uses ``yaml.safe_load`` so only plain
    scalars/containers are accepted (no arbitrary object construction).
    """
    return from_dict(cls, yaml.safe_load(text))
