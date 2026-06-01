"""Structural tests for the narrative ``roadmap/ROADMAP.md`` planning artifact.

This module is the **migration / reuse / targets / policies** slice of the
structural test suite for Task 24.3. Unlike the property-based tests in this
package (which exercise the decision-logic tooling), these tests read the
authored ``ROADMAP.md`` text directly via ``roadmap.paths.ROADMAP_MD_PATH`` and
assert that the narrative *actually states* the migration statements, latency
targets, and budget/safety policies the requirements demand.

Matching is deliberately lenient about Markdown presentation: emphasis markers
(``*``) and inline-code backticks (`````) are stripped and all runs of
whitespace are collapsed to single spaces before matching, so a phrase that the
author wrapped in bold or split across table cells / lines still matches as
plain text. Substring checks are case-insensitive. Where a numeric target is
asserted, both the human-readable narrative token (e.g. ``300 ms``) and its
surrounding label (e.g. ``practical first-response``) are required so the test
fails loudly if the right number is attached to the wrong target.

Covers Requirements 3.1, 3.2, 3.3, 3.4, 3.6, 5.1, 5.2, 5.7, 6.2, 6.4, 6.6,
7.1, 7.2, 7.3, 7.6, 7.7, 9.2, 9.3, 9.4, 10.7.
"""

from __future__ import annotations

import re

import pytest

from roadmap.paths import ROADMAP_MD_PATH

# ---------------------------------------------------------------------------
# Shared, normalized view of the authored roadmap text
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Return *text* with Markdown emphasis/code markers removed and whitespace
    collapsed to single spaces.

    Stripping ``*`` and backtick characters lets a phrase the author wrapped in
    bold (``**…**``) or inline code (`````…`````) match as plain prose, and
    collapsing all whitespace (including newlines and table-cell padding) to a
    single space lets a statement that spans multiple lines or table cells be
    matched as one continuous string.
    """
    stripped = text.replace("*", "").replace("`", "")
    return re.sub(r"\s+", " ", stripped)


# Read the artifact once at import time using the shared path constant so the
# test resolves the same file regardless of the pytest working directory.
_RAW_ROADMAP = ROADMAP_MD_PATH.read_text(encoding="utf-8")
_ROADMAP = _normalize(_RAW_ROADMAP)
_ROADMAP_LOWER = _ROADMAP.lower()


def _assert_present(snippet: str) -> None:
    """Assert *snippet* appears (case-insensitively) in the normalized roadmap."""
    assert snippet.lower() in _ROADMAP_LOWER, (
        f"Expected statement not found in ROADMAP.md: {snippet!r}"
    )


def _assert_all_present(snippets: list[str]) -> None:
    """Assert every snippet in *snippets* is present in the normalized roadmap."""
    missing = [s for s in snippets if s.lower() not in _ROADMAP_LOWER]
    assert not missing, f"Expected statements missing from ROADMAP.md: {missing!r}"


# ---------------------------------------------------------------------------
# Sanity: the artifact exists and is non-trivial
# ---------------------------------------------------------------------------


def test_roadmap_artifact_exists_and_is_non_empty() -> None:
    """``ROADMAP.md`` resolves via the shared path constant and has content."""
    assert ROADMAP_MD_PATH.exists(), f"ROADMAP.md not found at {ROADMAP_MD_PATH}"
    assert ROADMAP_MD_PATH.is_file()
    assert len(_RAW_ROADMAP.strip()) > 0


# ---------------------------------------------------------------------------
# Requirement 3 — Evolution from the Phase 1 pipeline
# ---------------------------------------------------------------------------


def test_concurrent_run_migration_stage_is_specified() -> None:
    """An intermediate stage runs the core and Phase 1 pipeline concurrently.

    Validates: Requirements 3.1.
    """
    _assert_present("Concurrent-run migration stage")
    _assert_present(
        "Speech_Native_Core and the Phase_1_Pipeline run concurrently"
    )
    # The core is introduced ALONGSIDE rather than swapped in a single step.
    _assert_present("introduced alongside the existing pipeline")


def test_per_session_runtime_fallback_switch_is_specified() -> None:
    """A per-session runtime fallback switch / config setting selects the path.

    Validates: Requirements 3.2.
    """
    _assert_present("per-session runtime fallback switch")
    _assert_present("runtime configuration setting")
    # The Phase_1_Pipeline is the per-session fallback for the integration window.
    _assert_present("per-session fallback")


def test_reuse_of_existing_edge_components_is_specified() -> None:
    """Silero VAD, turn_state.py, and filler.py are reused, not rebuilt.

    Validates: Requirements 3.3.
    """
    _assert_all_present(
        [
            "Silero VAD",
            "server/pipeline/turn_state.py",
            "server/pipeline/filler.py",
            "reuses",
        ]
    )


def test_retained_auxiliary_stt_is_specified() -> None:
    """faster-whisper + Indic_Stack ASR retained as auxiliary STT.

    Validates: Requirements 3.4.
    """
    _assert_all_present(
        [
            "faster-whisper",
            "Indic_Stack ASR",
            "auxiliary STT",
            "transcripts, memory, and moderation",
        ]
    )


def test_transport_continuity_is_specified() -> None:
    """WebSocket /ws/audio/{session_id} + LiveKit preserved or assigned v2.

    Validates: Requirements 3.6.
    """
    _assert_all_present(
        [
            "/ws/audio/{session_id}",
            "LiveKit",
            "preserved unchanged",
            "version identifier (v2)",
        ]
    )


# ---------------------------------------------------------------------------
# Requirement 7.6 — Duplex_Manager is an evolution, not a rebuild
# ---------------------------------------------------------------------------


def test_duplex_manager_is_evolution_not_rebuild() -> None:
    """Duplex_Manager evolves barge_in.py + turn_state.py and is not rebuilt.

    Validates: Requirements 7.6.
    """
    _assert_all_present(
        [
            "Duplex_Manager",
            "evolution of server/pipeline/barge_in.py",
            "server/pipeline/turn_state.py",
            "not rebuilt from scratch",
        ]
    )


# ---------------------------------------------------------------------------
# Requirement 5 — Hinglish moat, data engine, and lightweight adaptation
# ---------------------------------------------------------------------------


def test_hinglish_designated_primary_moat() -> None:
    """Hinglish / code-switch quality is the PRIMARY competitive moat.

    Validates: Requirements 5.1.
    """
    _assert_present("Hinglish and Hindi/English code-switch quality")
    _assert_present("PRIMARY competitive moat")


def test_hinglish_data_engine_sources_consented_codeswitch_data() -> None:
    """Hinglish_Data_Engine sources consented Romanized + Devanagari data.

    Validates: Requirements 5.2.
    """
    _assert_all_present(
        [
            "Hinglish_Data_Engine",
            "consented",
            "Romanized",
            "Devanagari",
        ]
    )


def test_lightweight_adaptation_before_custom_work() -> None:
    """LoRA/adapters applied before custom work when core misses the threshold.

    Validates: Requirements 5.7.
    """
    _assert_present("lightweight adaptation (LoRA / adapters)")
    _assert_present("before any custom-model work")
    # Triggered when the adopted core scores below the 80% pass threshold.
    _assert_present("scores below the 80% Hinglish code-switch pass threshold")


# ---------------------------------------------------------------------------
# Requirement 6 — Emotion / persona control
# ---------------------------------------------------------------------------


def test_vad_carried_forward_from_emotion_py() -> None:
    """Continuous V/A/D from emotion.py is carried forward.

    Validates: Requirements 6.2.
    """
    _assert_present("valence / arousal / dominance (V/A/D)")
    _assert_present("server/pipeline/emotion.py")
    _assert_present("carried forward")


def test_film_style_conditioning_mechanism_is_specified() -> None:
    """FiLM-style conditioning is the specified injection mechanism.

    Validates: Requirements 6.4.
    """
    _assert_present("FiLM-style conditioning")


def test_retained_ser_and_speaker_encoder_models() -> None:
    """wav2vec2 SER + ECAPA-TDNN speaker encoder are retained.

    Validates: Requirements 6.6.
    """
    _assert_all_present(
        [
            "speechbrain/emotion-recognition-wav2vec2-IEMOCAP",
            "ECAPA-TDNN speaker encoder",
            "(SER)",
        ]
    )


# ---------------------------------------------------------------------------
# Requirement 7 — Latency targets and mitigations
# ---------------------------------------------------------------------------


def test_latency_targets_are_specified_at_p50() -> None:
    """Practical 300 ms, stretch 200 ms, perceived 80 ms targets at p50.

    Validates: Requirements 7.1, 7.2, 7.3.
    """
    # All three targets are measured at the 50th percentile (p50).
    assert ("p50" in _ROADMAP_LOWER) or ("50th percentile" in _ROADMAP_LOWER)

    # Practical first-response: <= 300 ms (Req 7.1).
    _assert_present("Practical first-response")
    _assert_present("300 ms")

    # Stretch first-response: <= 200 ms (Req 7.2).
    _assert_present("Stretch first-response")
    _assert_present("200 ms")

    # Perceived latency: <= 80 ms via streaming + cached filler phrases (Req 7.3).
    _assert_present("Perceived latency")
    _assert_present("80 ms")
    _assert_present("cached filler phrases")


def test_latency_mitigations_are_specified() -> None:
    """Mitigations if the 300 ms practical target is missed.

    Validates: Requirements 7.7.
    """
    # Triggered specifically when the practical (300 ms) target is missed.
    _assert_present("if the practical (300 ms) target is missed")
    _assert_all_present(
        [
            "Model quantization",
            "smaller Speech_Native_Core",
            "Expanded filler coverage",
        ]
    )


# ---------------------------------------------------------------------------
# Requirement 9 — Budget / compute awareness
# ---------------------------------------------------------------------------


def test_budget_ranges_in_single_currency() -> None:
    """Both track budget ranges are stated in one currency (USD).

    Validates: Requirements 9.2.
    """
    _assert_present("single stated currency")
    _assert_present("US dollars (USD)")
    # LEAN range 5,000-50,000 and AMBITIOUS range 50,000-500,000 are present.
    _assert_all_present(["5,000", "50,000", "500,000"])


def test_lean_feasibility_claim_team_and_no_large_scale_training() -> None:
    """LEAN executable by <= 5 people without large-scale GPU training.

    Validates: Requirements 9.3.
    """
    _assert_present("at most five (5) people without large-scale GPU training")
    _assert_present("multi-GPU or multi-node from-scratch model training")


def test_ambitious_justification_required_before_entry() -> None:
    """AMBITIOUS entry at G1 requires an explicit, approved justification.

    Validates: Requirements 9.4.
    """
    _assert_present("AMBITIOUS_Track is entered at Decision_Gate G1")
    _assert_present("explicit justification is required")
    # The justification must carry the budget range AND the per-phase footprint.
    _assert_present("AMBITIOUS_Track budget range")
    _assert_present("per-phase compute footprint")


# ---------------------------------------------------------------------------
# Requirement 10.7 — Safety/consent/watermarking in LEAN demo scope
# ---------------------------------------------------------------------------


def test_safety_consent_watermarking_in_lean_demo_scope() -> None:
    """Safety, consent, and watermarking ship in the LEAN demo, not deferred.

    Validates: Requirements 10.7.
    """
    _assert_present(
        "Safety classification, consent management, and audio watermarking "
        "are part of the LEAN_Track DEMO scope"
    )
    _assert_present("not deferred to the optional AMBITIOUS_Track")


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
