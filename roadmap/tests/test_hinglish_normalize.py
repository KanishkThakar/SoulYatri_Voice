"""Property-based test for Hinglish transliteration normalization.

This module implements the design's **Property 8: Transliteration determinism
and unmapped-token handling** for
:meth:`roadmap.hinglish.HinglishDataEngine.normalize`, which returns a
:class:`roadmap.models.runtime.NormalizationResult`.

Property 8 (design ``Correctness Properties``):

    For any input string, normalizing it repeatedly always produces the
    identical normalized output (deterministic, in both input-normalization and
    output-rendering directions); and for any input token that has no entry in
    the transliteration mapping, that token appears unchanged in the normalized
    output and is also reported in the unmapped-token list.

The test is split into the two halves the property describes, each tagged with
the same Property 8 marker:

- **Determinism (Requirement 5.5).** ``normalize(text)`` called twice on one
  engine yields equal results, and a *freshly constructed* engine yields the
  same result for the same text -- proving there is no shared mutable state or
  hidden randomness. Inputs are arbitrary text strings *and* strings built from
  the known mapping so both the mapped and unmapped code paths are exercised.

- **Unmapped handling (Requirement 5.8).** Inputs mix three kinds of token so
  both branches are covered: known Romanized mapping keys, known Devanagari
  forms, and random Latin tokens guaranteed *not* to be in the mapping (filtered
  against both the Romanized keys and the Devanagari values). Each random
  non-mapped token must be retained unchanged in ``normalized_text`` *and*
  reported in ``unmapped_tokens``; each recognized token (Romanized key ->
  Devanagari value, or already-Devanagari -> unchanged) must be absent from
  ``unmapped_tokens``.

Validates: Requirements 5.5, 5.8.
"""

from __future__ import annotations

import string

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.hinglish import DEFAULT_ROMANIZED_TO_DEVANAGARI, HinglishDataEngine

#: The Romanized keys recognized by the built-in mapping.
KNOWN_ROMAN_KEYS = sorted(DEFAULT_ROMANIZED_TO_DEVANAGARI.keys())

#: The distinct Devanagari forms the mapping produces (recognized passthrough
#: tokens). Deduplicated because several spellings can share one form.
KNOWN_DEVA_FORMS = sorted(set(DEFAULT_ROMANIZED_TO_DEVANAGARI.values()))

#: Set of every recognized token in *either* direction, used to guarantee a
#: generated "unmapped" token really has no mapping entry.
_ALL_MAPPED_TOKENS = set(DEFAULT_ROMANIZED_TO_DEVANAGARI.keys()) | set(
    DEFAULT_ROMANIZED_TO_DEVANAGARI.values()
)

#: Random Latin-script tokens guaranteed NOT to be a mapping key or a Devanagari
#: form. Latin letters only (so the token is a single whitespace-delimited word)
#: and explicitly filtered against every recognized token.
unmapped_tokens = st.text(
    alphabet=string.ascii_letters, min_size=1, max_size=10
).filter(lambda token: token not in _ALL_MAPPED_TOKENS)


@st.composite
def mixed_token_lists(draw: st.DrawFn) -> list[tuple[str, str]]:
    """Generate a list of ``(kind, token)`` items mixing all three branches.

    ``kind`` is one of ``"known"`` (a Romanized mapping key), ``"deva"`` (an
    already-recognized Devanagari form), or ``"unmapped"`` (a random Latin token
    with no mapping entry). Mixing the three within one list ensures every
    example exercises both the mapped and the unmapped branch of
    :meth:`HinglishDataEngine.normalize`.
    """
    count = draw(st.integers(min_value=1, max_value=8))
    items: list[tuple[str, str]] = []
    for _ in range(count):
        kind = draw(st.sampled_from(("known", "deva", "unmapped")))
        if kind == "known":
            token = draw(st.sampled_from(KNOWN_ROMAN_KEYS))
        elif kind == "deva":
            token = draw(st.sampled_from(KNOWN_DEVA_FORMS))
        else:
            token = draw(unmapped_tokens)
        items.append((kind, token))
    return items


def _join(items: list[tuple[str, str]]) -> str:
    """Join the tokens of an item list into single-space-separated text."""
    return " ".join(token for _, token in items)


# Feature: speech-native-voice-roadmap, Property 8: Transliteration determinism and unmapped-token handling
@settings(max_examples=100)
@given(
    text=st.one_of(
        st.text(),
        mixed_token_lists().map(_join),
    )
)
def test_property_8_normalize_is_deterministic(text: str) -> None:
    """Property 8 (determinism half): same input always normalizes identically.

    Requirement 5.5: the mapping is deterministic, so repeated calls -- and a
    fresh engine instance -- must produce byte-for-byte equal results, proving
    there is no shared mutable state or randomness.

    Validates: Requirements 5.5.
    """
    engine = HinglishDataEngine()

    first = engine.normalize(text)
    second = engine.normalize(text)

    # Repeated calls on the same engine are identical (normalized_text AND
    # unmapped_tokens both compared via dataclass equality).
    assert second == first
    assert second.normalized_text == first.normalized_text
    assert second.unmapped_tokens == first.unmapped_tokens

    # A freshly constructed engine yields the same result -> no shared state.
    fresh = HinglishDataEngine()
    third = fresh.normalize(text)
    assert third == first


# Feature: speech-native-voice-roadmap, Property 8: Transliteration determinism and unmapped-token handling
@settings(max_examples=100)
@given(items=mixed_token_lists())
def test_property_8_unmapped_tokens_retained_and_flagged(
    items: list[tuple[str, str]],
) -> None:
    """Property 8 (unmapped half): unmapped tokens are kept and flagged.

    Requirement 5.8: a token with no mapping entry is retained unchanged in
    ``normalized_text`` and reported in ``unmapped_tokens``. Recognized tokens
    (Romanized key -> Devanagari value, or already-Devanagari -> unchanged) are
    normalized and never flagged.

    Validates: Requirements 5.8.
    """
    engine = HinglishDataEngine()
    text = _join(items)

    result = engine.normalize(text)

    # Build the expected normalized tokens and the expected unmapped list from
    # the known item kinds, then assert the engine reproduces them exactly.
    expected_tokens: list[str] = []
    expected_unmapped: list[str] = []
    for kind, token in items:
        if kind == "known":
            expected_tokens.append(DEFAULT_ROMANIZED_TO_DEVANAGARI[token])
        elif kind == "deva":
            expected_tokens.append(token)
        else:  # "unmapped"
            expected_tokens.append(token)
            expected_unmapped.append(token)

    # Spacing is preserved, so the rebuilt text is the mapped tokens rejoined.
    assert result.normalized_text == " ".join(expected_tokens)
    # Unmapped tokens are reported in order of occurrence, and ONLY the
    # genuinely unmapped tokens are reported.
    assert result.unmapped_tokens == expected_unmapped

    # Per-token assertions spelling out Requirement 5.8 directly.
    output_tokens = result.normalized_text.split()
    for kind, token in items:
        if kind == "known":
            deva = DEFAULT_ROMANIZED_TO_DEVANAGARI[token]
            # Recognized Romanized token is replaced by its Devanagari form...
            assert deva in output_tokens
            # ...and is NOT flagged as unmapped.
            assert token not in result.unmapped_tokens
        elif kind == "deva":
            # Already-recognized Devanagari form is retained unchanged and not
            # flagged.
            assert token in output_tokens
            assert token not in result.unmapped_tokens
        else:  # "unmapped"
            # Unmapped token: retained unchanged in the output AND flagged.
            assert token in output_tokens
            assert token in result.unmapped_tokens
