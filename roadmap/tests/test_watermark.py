"""Property-based test for watermarking on every output path.

This module holds the Hypothesis property test for
**Property 12: Watermark on every output path** (task 19.2) covering
:meth:`roadmap.safety_guard.SafetyGuard.guard_output` and
:meth:`roadmap.safety_guard.SafetyGuard.evaluate_output`.

Property 12 (design "Correctness Properties")
---------------------------------------------
*For any* synthesized speech output produced on any output path, including
fallback paths, the applied audio watermark is present and is reported as
detected by the watermark detector.

Concretely (Requirement 10.2): every synthesized output, on *every* path
(``speech_native_core``, ``phase_1_fallback``, ``tts_fallback``, or any other
non-empty path identifier), is watermarked and verified — yielding
``compliant=True`` and ``emitted=True``. An output whose watermark cannot be
verified is instead flagged non-compliant (``compliant=False``) and withheld
(``emitted=False``) rather than emitted.

Validates: Requirements 10.2
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from roadmap.safety_guard import (
    OUTPUT_PATHS,
    EmissionResult,
    SafetyGuard,
    SynthesizedOutput,
    WatermarkDetector,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
def _content() -> st.SearchStrategy[str]:
    """Arbitrary synthesized-output payload, including the empty string.

    The watermark guarantee is unconditional on content, so the full text
    space (including ``""`` and whitespace-only payloads) is fair game.
    """
    return st.text()


def _non_empty_path() -> st.SearchStrategy[str]:
    """An arbitrary non-empty (non-whitespace) output-path identifier.

    :class:`SynthesizedOutput` rejects paths that are empty or whitespace-only,
    so the strategy filters those out to stay within the accepted input space
    while still exercising arbitrary path strings beyond the canonical ones.
    """
    return st.text(min_size=1).filter(lambda s: bool(s.strip()))


def _any_path() -> st.SearchStrategy[str]:
    """A canonical :data:`OUTPUT_PATHS` member OR an arbitrary non-empty path.

    Sampling from both ensures the every-path guarantee is asserted on the
    documented core/fallback paths *and* on arbitrary accepted path strings.
    """
    return st.one_of(st.sampled_from(OUTPUT_PATHS), _non_empty_path())


class _FailingDetector(WatermarkDetector):
    """A detector whose verification always fails.

    Models the "watermark cannot be verified" case: even a correctly applied,
    well-formed watermark is reported as *not detected*, so the guard must flag
    the output non-compliant and withhold it.
    """

    def detect(self, output: SynthesizedOutput) -> bool:  # noqa: D102
        return False


# ---------------------------------------------------------------------------
# Property 12 — the watermark is present and detected on every path
# ---------------------------------------------------------------------------
# Feature: speech-native-voice-roadmap, Property 12: Watermark on every output path
@settings(max_examples=100)
@given(content=_content(), path=_any_path())
def test_property_12_watermark_on_every_output_path(
    content: str, path: str
) -> None:
    """Property 12: every output on every path is watermarked and emittable.

    Validates: Requirements 10.2
    """
    guard = SafetyGuard()
    result = guard.guard_output(content, path)

    assert isinstance(result, EmissionResult)

    # The output carries a present, non-empty watermark on this path.
    assert result.output.is_watermarked
    assert result.output.watermark
    assert str(result.output.watermark).strip()

    # The watermark is reported as detected -> compliant and emitted.
    assert result.watermark_detected is True
    assert result.compliant is True
    assert result.emitted is True

    # The output faithfully echoes the content/path it was produced for.
    assert result.output.content == content
    assert result.output.path == path


# Feature: speech-native-voice-roadmap, Property 12: Watermark on every output path
@settings(max_examples=100)
@given(content=_content(), path=_any_path())
def test_property_12_holds_on_canonical_and_fallback_paths(
    content: str, path: str
) -> None:
    """The guarantee holds on the documented core AND fallback paths.

    Explicitly sweeps every canonical path — including the Phase 1 and TTS
    *fallback* paths — to assert the watermark guarantee is not special-cased
    to the core path.

    Validates: Requirements 10.2
    """
    guard = SafetyGuard()
    for canonical_path in OUTPUT_PATHS:
        result = guard.guard_output(content, canonical_path)
        assert result.output.is_watermarked
        assert result.watermark_detected is True
        assert result.compliant is True
        assert result.emitted is True
        assert result.output.path == canonical_path


# ---------------------------------------------------------------------------
# Property 12 — an unverifiable watermark is withheld, not emitted
# ---------------------------------------------------------------------------
# Feature: speech-native-voice-roadmap, Property 12: Watermark on every output path
@settings(max_examples=100)
@given(content=_content(), path=_any_path())
def test_property_12_unverifiable_watermark_is_withheld(
    content: str, path: str
) -> None:
    """An output whose watermark cannot be verified is flagged and withheld.

    With a detector that never confirms a watermark, the guard must mark the
    output non-compliant and refuse to emit it on every path, rather than
    releasing an unverified output.

    Validates: Requirements 10.2
    """
    guard = SafetyGuard(watermark_detector=_FailingDetector())
    result = guard.guard_output(content, path)

    # The detector reports failure -> non-compliant and withheld.
    assert result.watermark_detected is False
    assert result.compliant is False
    assert result.emitted is False


# Feature: speech-native-voice-roadmap, Property 12: Watermark on every output path
@settings(max_examples=100)
@given(content=_content(), path=_any_path())
def test_property_12_tampered_watermark_is_withheld(
    content: str, path: str
) -> None:
    """A tampered watermark fails verification and the output is withheld.

    Builds a watermarked output, tampers the watermark token so it no longer
    matches what the (honest) detector expects, then evaluates it: the guard
    re-applies/verifies and must withhold the output, never emit a tampered
    one.

    Validates: Requirements 10.2
    """
    guard = SafetyGuard()
    output = SynthesizedOutput(content=content, path=path)
    guard.apply_watermark(output)

    # Tamper: replace the verified watermark with a non-matching token.
    output.watermark = f"{output.watermark}-TAMPERED"

    # Verify directly against the honest detector (no re-application).
    result = guard._evaluate_compliance(output)
    assert result.watermark_detected is False
    assert result.compliant is False
    assert result.emitted is False
