"""Structural tests for the narrative roadmap's enumerations and designations.

These are *structural/example* tests (plain ``pytest``) that read the authored
narrative artifact ``roadmap/ROADMAP.md`` (resolved via
``roadmap.paths.ROADMAP_MD_PATH``) and assert that the model/codec/dataset
enumerations and the weighted-selection table the design mandates are actually
present in the document text.

They guard the content authored in Task 23 (sections 5 and 8 of the roadmap)
against the following acceptance criteria:

- **Req 2.2** — the verified 2026 Candidate_Model enumeration.
- **Req 2.3** — the weighted selection table (weights sum to 100, per-criterion
  minimum thresholds documented).
- **Req 2.5** — ``sesame/csm-1b`` and the TTS_Fallback designated
  reference/fallback only (not the primary backbone).
- **Req 2.6** — ``kyutai/mimi`` designated the primary Codec_Component with
  ``neuphonic/neucodec`` / ``HKUSTAudio/xcodec2`` named as alternatives.
- **Req 5.3** — the verified Indic_Stack resources.
- **Req 8.1** — the Benchmark_Suite families.
- **Req 8.6** — the competitive comparison targets.

Assertions are case-insensitive substring / regex checks on the document text
where reasonable, so they stay robust to incidental wording changes while still
proving each required item is named.
"""

from __future__ import annotations

import re

import pytest

from roadmap.paths import ROADMAP_MD_PATH


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def doc() -> str:
    """The raw ``ROADMAP.md`` text, read via the ``ROADMAP_MD_PATH`` constant."""
    assert ROADMAP_MD_PATH.exists(), (
        f"ROADMAP.md not found at {ROADMAP_MD_PATH}; the narrative artifact "
        "(Task 23) must exist for the structural tests to run."
    )
    return ROADMAP_MD_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc_lower(doc: str) -> str:
    """Lower-cased document text for case-insensitive substring checks."""
    return doc.lower()


def _assert_all_present(doc_lower: str, needles, *, context: str) -> None:
    """Assert every needle appears (case-insensitively) in the document."""
    missing = [n for n in needles if n.lower() not in doc_lower]
    assert not missing, f"{context}: missing from ROADMAP.md: {missing}"


def _section(doc: str, start_marker: str, *end_markers: str) -> str:
    """Return the slice of ``doc`` from ``start_marker`` to the first end marker."""
    start = doc.find(start_marker)
    assert start != -1, f"section marker not found in ROADMAP.md: {start_marker!r}"
    rest = doc[start + len(start_marker):]
    end = len(rest)
    for marker in end_markers:
        idx = rest.find(marker)
        if idx != -1:
            end = min(end, idx)
    return rest[:end]


# Matches a weighted-selection table row whose criterion name is in backticks,
# captures its integer weight and its minimum-threshold cell. The bold
# ``**Total**`` row is intentionally NOT matched (no backticked criterion).
_WEIGHT_ROW_RE = re.compile(
    r"\|\s*`(?P<crit>[A-Za-z_]+)`\s*\|\s*(?P<weight>\d+)\s*\|\s*(?P<minimum>[^|]+?)\s*\|"
)

# A documented per-criterion minimum threshold, e.g. "≥ 60" or ">= 60" or "> 40".
_MIN_THRESHOLD_RE = re.compile(r"(?:≥|>=|>)\s*\d+")


# ---------------------------------------------------------------------------
# Req 2.2 — Candidate_Model enumeration
# ---------------------------------------------------------------------------
def test_candidate_models_enumerated(doc_lower: str) -> None:
    """The verified 2026 Candidate_Models are enumerated (Req 2.2)."""
    candidates = [
        "kyutai/moshiko-pytorch-bf16",
        "kyutai/moshika-pytorch-bf16",
        "Qwen/Qwen3-Omni-30B-A3B-Instruct",
        "zai-org/glm-4-voice-9b",
        "sesame/csm-1b",
        "LiquidAI/LFM2.5-Audio-1.5B",
    ]
    _assert_all_present(doc_lower, candidates, context="Candidate_Model enumeration (Req 2.2)")


# ---------------------------------------------------------------------------
# Req 2.6 — Codec primary + alternatives
# ---------------------------------------------------------------------------
def test_codec_primary_and_alternatives(doc: str, doc_lower: str) -> None:
    """``kyutai/mimi`` is the primary codec; the two alternatives are named (Req 2.6)."""
    # All three codecs must be named.
    _assert_all_present(
        doc_lower,
        ["kyutai/mimi", "neuphonic/neucodec", "HKUSTAudio/xcodec2"],
        context="Codec_Component enumeration (Req 2.6)",
    )

    # kyutai/mimi must be designated PRIMARY: assert "primary" appears near the
    # mimi reference (same sentence / list item), case-insensitively.
    mimi_primary = re.search(
        r"primary[^\n]*kyutai/mimi|kyutai/mimi[^\n]*primary",
        doc,
        flags=re.IGNORECASE,
    )
    assert mimi_primary, "ROADMAP.md must designate `kyutai/mimi` as the PRIMARY codec (Req 2.6)."

    # The other two must be presented as alternatives.
    alternatives = re.search(
        r"alternativ[^\n]*(neuphonic/neucodec|HKUSTAudio/xcodec2)",
        doc,
        flags=re.IGNORECASE,
    )
    assert alternatives, (
        "ROADMAP.md must name `neuphonic/neucodec` and `HKUSTAudio/xcodec2` as "
        "codec alternatives (Req 2.6)."
    )


# ---------------------------------------------------------------------------
# Req 2.5 — csm-1b + TTS_Fallback are reference / fallback only
# ---------------------------------------------------------------------------
def test_csm_and_tts_fallback_are_reference_only(doc: str, doc_lower: str) -> None:
    """``sesame/csm-1b`` and the TTS_Fallback are reference/fallback only (Req 2.5)."""
    # csm-1b must be described as reference/fallback (not the primary backbone).
    csm_reference = re.search(
        r"(reference|fallback)[^\n]*csm-1b|csm-1b[^\n]*(reference|fallback)",
        doc,
        flags=re.IGNORECASE,
    )
    assert csm_reference, (
        "ROADMAP.md must describe `sesame/csm-1b` as a reference/fallback "
        "generator rather than the primary backbone (Req 2.5)."
    )

    # The TTS_Fallback options must be enumerated.
    tts_fallbacks = [
        "hexgrad/Kokoro-82M",
        "bosonai/higgs-audio-v2",
        "SparkAudio/Spark-TTS",
        "kyutai/tts-1.6b",
    ]
    _assert_all_present(doc_lower, tts_fallbacks, context="TTS_Fallback enumeration (Req 2.5)")

    # The notion of a TTS fallback must be named in the document.
    assert "tts_fallback" in doc_lower or "tts fallback" in doc_lower, (
        "ROADMAP.md must reference the TTS_Fallback designation (Req 2.5)."
    )


# ---------------------------------------------------------------------------
# Req 5.3 — Indic_Stack resources
# ---------------------------------------------------------------------------
def test_indic_stack_resources_enumerated(doc_lower: str) -> None:
    """The verified Indic_Stack resources are enumerated (Req 5.3)."""
    indic_stack = [
        "ai4bharat/indic-conformer-600m-multilingual",
        "shunyalabs/zero-stt-hinglish",
        "ai4bharat/IndicF5",
        "ai4bharat/indic-parler-tts",
        "ai4bharat/IndicVoices",
    ]
    _assert_all_present(doc_lower, indic_stack, context="Indic_Stack resources (Req 5.3)")


# ---------------------------------------------------------------------------
# Req 8.1 — Benchmark families
# ---------------------------------------------------------------------------
def test_benchmark_families_enumerated(doc_lower: str) -> None:
    """The Benchmark_Suite families are enumerated (Req 8.1)."""
    families = [
        "VoiceBench",
        "EmergentTTS-Eval",
        "Seed-TTS-eval",
        "MUSHRA",
        "Speech Arena",
    ]
    _assert_all_present(doc_lower, families, context="Benchmark families (Req 8.1)")


# ---------------------------------------------------------------------------
# Req 8.6 — Competitive comparison targets
# ---------------------------------------------------------------------------
def test_competitive_targets_enumerated(doc_lower: str) -> None:
    """The competitive comparison targets are enumerated (Req 8.6)."""
    targets = ["ElevenLabs", "Hume", "Rumik", "Sarvam"]
    _assert_all_present(doc_lower, targets, context="Competitive comparison targets (Req 8.6)")


# ---------------------------------------------------------------------------
# Req 2.3 — Weighted selection table (weights sum to 100, per-criterion minimum)
# ---------------------------------------------------------------------------
def test_selection_weight_table_sums_to_100_with_minimums(doc: str) -> None:
    """The six selection criteria weigh 100 in total and each has a minimum (Req 2.3)."""
    # Isolate the weighted-selection criteria section (5.3) so the row regex
    # only sees that table and not other backticked-name tables elsewhere.
    section = _section(doc, "### 5.3", "### 5.4", "\n## ")

    # The table must declare a per-criterion minimum-threshold column.
    assert re.search(r"minimum", section, flags=re.IGNORECASE), (
        "Selection table (section 5.3) must document a per-criterion minimum "
        "pass-threshold column (Req 2.3)."
    )

    rows = list(_WEIGHT_ROW_RE.finditer(section))
    criteria = {m.group("crit"): m for m in rows}

    expected_criteria = {
        "streaming_latency",
        "hinglish_capability",
        "full_duplex",
        "license_permissiveness",
        "vram_footprint",
        "community_activity",
    }
    assert expected_criteria.issubset(criteria.keys()), (
        "Selection table (Req 2.3) must list the six weighted criteria; "
        f"found {sorted(criteria.keys())}, expected superset of "
        f"{sorted(expected_criteria)}."
    )

    # Collect the weights for exactly the six expected criteria.
    weights = {c: int(criteria[c].group("weight")) for c in expected_criteria}

    # The six weight values must be present and sum to 100.
    assert sorted(weights.values()) == sorted([25, 25, 20, 15, 10, 5]), (
        f"Selection weights must be the six values 25/25/20/15/10/5; got {weights}."
    )
    assert sum(weights.values()) == 100, (
        f"Selection weights must sum to 100 (Req 2.3); got {sum(weights.values())} "
        f"from {weights}."
    )

    # Every one of the six criteria must document a per-criterion minimum.
    for crit in expected_criteria:
        minimum_cell = criteria[crit].group("minimum")
        assert _MIN_THRESHOLD_RE.search(minimum_cell), (
            f"Criterion `{crit}` must document a numeric minimum pass threshold "
            f"(Req 2.3); got minimum cell {minimum_cell!r}."
        )

    # The table should also state the total of 100 explicitly.
    assert re.search(r"total\D+100", section, flags=re.IGNORECASE | re.DOTALL), (
        "Selection table (section 5.3) should state a Total of 100 (Req 2.3)."
    )
