"""Hinglish transliteration normalization (the code-switch data moat).

This module owns :class:`HinglishDataEngine`, the pure decision-logic component
behind the SoulYatri Hinglish_Data_Engine. For now it implements the
*transliteration interface* only:

    normalize(text) -> NormalizationResult{normalized_text, unmapped_tokens}

The engine uses a **deterministic** Romanized↔Devanagari mapping: the same input
string always produces the same normalized output (Requirement 5.5). The mapping
is applied for both *input normalization* (Romanized → Devanagari, the canonical
normalized form) and *output rendering* (Devanagari → Romanized), so it is kept
in both directions as instance attributes.

Tokens with no entry in the mapping are retained **unchanged** inside
``normalized_text`` and additionally reported in ``unmapped_tokens`` so they can
be flagged for review (Requirement 5.8).

In addition to normalization, the engine owns the **code-switch quality metric**
(Requirements 5.4, 5.6):

    score(input, output)        -> CodeSwitchScore
    within_tolerance(input, output) -> bool
    evaluate_benchmark(pairs)   -> BenchmarkResult
    benchmark_passes(score)     -> bool

The two governing constants are :data:`TOLERANCE_PCT` (= 15 percentage points,
the within-tolerance band, Requirement 5.4) and :data:`BENCHMARK_PASS_PCT`
(= 80%, the evaluation-set pass threshold, Requirement 5.6). They are also
exposed under the longer names :data:`TOLERANCE_PP` and
:data:`BENCHMARK_PASS_THRESHOLD`; each ``_PCT`` name aliases the same value.

H/E ratio definition
---------------------
The **Hindi-to-English (H/E) ratio** of a piece of text is defined as a
*percentage*::

    H/E ratio = 100 * hindi_tokens / (hindi_tokens + english_tokens)

where each word token (whitespace/punctuation-delimited) is classified as:

- **Hindi** — the token contains any Devanagari-script character, OR (after
  case-folding) it is a recognized Hinglish-Hindi token in the engine's
  transliteration mapping (i.e. it has a Romanized→Devanagari entry, or it is a
  known Devanagari form). This reuses ``normalize()``'s mapping so the two stay
  consistent.
- **English** — a token written in Latin script that is *not* a recognized
  Hinglish-Hindi token.
- **Neither** — tokens with no Hindi/Latin letters (pure punctuation, pure
  digits, emoji, …) are ignored: they count toward neither numerator nor
  denominator.

The ratio is expressed on a ``0.0..100.0`` percentage scale. By convention, text
with **no** classifiable Hindi/English tokens has an H/E ratio of ``0.0`` (it is
treated as containing no Hindi).

Code-switch quality (per-pair) and benchmark pass rule
------------------------------------------------------
A single (input, output) response is **within tolerance** iff the absolute
difference between the output's H/E ratio and the input's H/E ratio is at most
**15 percentage points** (Requirement 5.4)::

    within_tolerance = |output_ratio - input_ratio| <= 15.0

:meth:`score` returns a structured :class:`CodeSwitchScore` carrying the input
ratio, output ratio, the absolute difference in percentage points, and the
``within_tolerance`` boolean. The per-pair **quality score** is expressed as a
percentage: ``100.0`` when within tolerance and ``0.0`` otherwise (a per-pair
pass/fail mapped onto the same percentage scale as the aggregate). The
:meth:`within_tolerance` helper returns just that boolean for callers that need
only the pass/fail decision for a single pair.

The **evaluation-set score** is the percentage of evaluated pairs that are
within tolerance::

    eval_set_score = 100 * (#within_tolerance pairs) / (#pairs)

A build **passes** the Hinglish benchmark iff the evaluation-set score is
**>= 80%** (Requirement 5.6). :meth:`benchmark_passes` applies that rule to a
precomputed evaluation-set score and :meth:`evaluate_benchmark` aggregates a set
of pairs into a :class:`BenchmarkResult` (per-pair scores + eval-set score +
pass flag).

Lightweight-adaptation (LoRA/adapters) hook
-------------------------------------------
Per Requirement 5.7, WHERE the adopted Speech_Native_Core scores **below** the
80% code-switch pass threshold, the roadmap specifies **lightweight adaptation
(LoRA / adapters) applied to the Hinglish_Data_Engine output** *before any
custom-model work is considered*. Concretely, when
``evaluate_benchmark(pairs).passes`` is ``False`` (eval-set score < 80%), the
remediation step is to fine-tune lightweight LoRA/adapter weights on the
Hinglish_Data_Engine's code-switch output — not to fork or pretrain a custom
model. Custom-model work (the AMBITIOUS track) remains gated behind that
lightweight-adaptation attempt. This hook is a *planning* designation surfaced
by :meth:`benchmark_passes` / :meth:`evaluate_benchmark`; the actual LoRA
training is downstream work this spec plans but does not execute.

Design references:
- design.md §5 "Hinglish Data Engine (``HinglishDataEngine``)"
- design.md "Property 7: Code-switch quality scoring and pass threshold"
- design.md "Property 8: Transliteration determinism and unmapped-token handling"

Forward-looking structure:
- The mapping is an **instance attribute** populated from a module-level default
  in :meth:`HinglishDataEngine.__init__`. The default table is externalized to
  the versioned ``roadmap/data/hinglish_map.json`` (Task 34.1) and loaded at
  import time into :data:`DEFAULT_ROMANIZED_TO_DEVANAGARI`; sourcing the table
  from data rather than an inline dict does not change the :meth:`normalize`
  logic.

Validates: Requirements 5.4, 5.5, 5.6, 5.7, 5.8.
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from typing import Iterable

from .models.runtime import NormalizationResult
from .paths import HINGLISH_MAP_PATH

__all__ = [
    "HinglishDataEngine",
    "CodeSwitchScore",
    "BenchmarkResult",
    "DEFAULT_ROMANIZED_TO_DEVANAGARI",
    "TOLERANCE_PP",
    "TOLERANCE_PCT",
    "BENCHMARK_PASS_THRESHOLD",
    "BENCHMARK_PASS_PCT",
    "LORA_ADAPTATION_HOOK",
]


# The deterministic Romanized → Devanagari mapping is **externalized** to the
# versioned data file ``roadmap/data/hinglish_map.json`` (Task 34.1) and loaded
# at import time into :data:`DEFAULT_ROMANIZED_TO_DEVANAGARI`. The JSON document
# has the shape ``{"version": "1.0", "mapping": {<roman>: <devanagari>, ...}}``;
# only the ``"mapping"`` object is consumed here. ``json.load`` preserves object
# key order (Python 3.7+), which is significant: when two Romanized spellings map
# to the same Devanagari form (e.g. ``"nahi"``/``"nahin"``), the *first* spelling
# in the file becomes the canonical Romanized rendering in the reverse map,
# keeping output deterministic.
#
# Loading the table here rather than building the engine's mapping inline keeps
# :meth:`normalize` unchanged while letting the table evolve as data. The
# in-memory ``DEFAULT_ROMANIZED_TO_DEVANAGARI`` constant remains importable and
# is exactly the mapping the default engine uses.


def _load_default_mapping(path=HINGLISH_MAP_PATH) -> dict[str, str]:
    """Load the Romanized → Devanagari mapping from the versioned JSON file.

    Reads ``path`` (default :data:`roadmap.paths.HINGLISH_MAP_PATH`) and returns
    its ``"mapping"`` object as an ordered ``dict``. ``json.load`` preserves the
    file's key order, so the first Romanized spelling for any shared Devanagari
    form remains canonical in the engine's reverse map.

    Args:
        path: Filesystem path to the JSON mapping document. Defaults to the
            packaged ``roadmap/data/hinglish_map.json``.

    Returns:
        The Romanized → Devanagari table as an order-preserving ``dict``.
    """
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    mapping = document["mapping"]
    return {str(roman): str(deva) for roman, deva in mapping.items()}


#: The deterministic, built-in Romanized → Devanagari mapping, loaded at import
#: time from the versioned ``roadmap/data/hinglish_map.json`` (Task 34.1). This
#: is the table the default :class:`HinglishDataEngine` (constructed with
#: ``mapping=None``) uses. Key order is preserved from the file so the reverse
#: (Devanagari → Romanized) rendering is deterministic.
DEFAULT_ROMANIZED_TO_DEVANAGARI: dict[str, str] = _load_default_mapping()

# Split that *preserves* the original whitespace runs as separate parts, so the
# exact spacing of the input is reproduced in ``normalized_text``. With a
# capturing group, ``re.split`` interleaves text tokens and whitespace runs.
_WHITESPACE_SPLIT = re.compile(r"(\s+)")

# Matches any Devanagari-script character (the Unicode Devanagari block,
# U+0900–U+097F). A token containing any such character is unambiguously Hindi.
_DEVANAGARI_CHAR = re.compile(r"[\u0900-\u097F]")

# Matches Latin-script letters (ASCII a–z/A–Z). Used to decide whether a token
# carries an "English" (Latin) word at all when classifying.
_LATIN_CHAR = re.compile(r"[A-Za-z]")

#: Code-switch tolerance band, in **percentage points**. A response is "within
#: tolerance" iff its H/E ratio is within this many percentage points of the
#: input's H/E ratio (Requirement 5.4).
TOLERANCE_PP: float = 15.0

#: Alias for :data:`TOLERANCE_PP` using the task's ``_PCT`` naming. The
#: code-switch tolerance is **15 percentage points** (Requirement 5.4); both
#: names refer to the same value.
TOLERANCE_PCT: float = TOLERANCE_PP

#: The Hinglish benchmark pass threshold, as a **percentage**. A build passes the
#: Hinglish code-switch benchmark iff its evaluation-set score is at or above
#: this value (Requirement 5.6).
BENCHMARK_PASS_THRESHOLD: float = 80.0

#: Alias for :data:`BENCHMARK_PASS_THRESHOLD` using the task's ``_PCT`` naming. A
#: build passes the Hinglish benchmark iff its evaluation-set score is **>= 80%**
#: (Requirement 5.6); both names refer to the same value.
BENCHMARK_PASS_PCT: float = BENCHMARK_PASS_THRESHOLD

# Punctuation/quote characters stripped from the edges of a token before
# classification, so e.g. ``"namaste,"`` and ``"(hello)"`` classify on their
# word content rather than their surrounding punctuation.
_EDGE_PUNCT = string.punctuation + "\u2018\u2019\u201c\u201d\u2013\u2014\u2026\u00bf\u00a1"

#: The lightweight-adaptation remediation designation surfaced when a build
#: scores below the 80% Hinglish code-switch pass threshold (Requirement 5.7).
LORA_ADAPTATION_HOOK: str = (
    "Hinglish code-switch score < 80%: apply lightweight adaptation "
    "(LoRA/adapters) to the Hinglish_Data_Engine output before any "
    "custom-model work is considered."
)


@dataclass(frozen=True)
class CodeSwitchScore:
    """The code-switch quality result for one (input, output) pair.

    Ratios are H/E percentages on a ``0.0..100.0`` scale (see the module
    docstring for the H/E ratio definition). ``difference_pp`` is the absolute
    gap between the two ratios expressed in **percentage points**.

    Attributes:
        input_ratio: The input text's H/E ratio (percentage).
        output_ratio: The response text's H/E ratio (percentage).
        difference_pp: ``abs(output_ratio - input_ratio)`` in percentage points.
        within_tolerance: ``True`` iff ``difference_pp <= 15.0`` (Requirement
            5.4).
        quality: The per-pair quality score as a percentage — ``100.0`` when
            within tolerance, ``0.0`` otherwise — on the same scale as the
            evaluation-set aggregate.
    """

    input_ratio: float
    output_ratio: float
    difference_pp: float
    within_tolerance: bool
    quality: float


@dataclass(frozen=True)
class BenchmarkResult:
    """The aggregate Hinglish code-switch benchmark result over a pair set.

    Attributes:
        per_pair: The per-pair :class:`CodeSwitchScore` results, in input order.
        within_tolerance_count: Number of pairs that were within tolerance.
        total: Total number of pairs evaluated.
        eval_set_score: The evaluation-set score as a percentage —
            ``100 * within_tolerance_count / total`` (``0.0`` for an empty set).
        passes: ``True`` iff ``eval_set_score >= 80.0`` (Requirement 5.6).
        adaptation_hook: Human-readable designation of the next remediation step
            when the benchmark does **not** pass: lightweight LoRA/adapter
            adaptation on the Hinglish_Data_Engine output, applied *before* any
            custom-model work (Requirement 5.7). ``None`` when the build passes.
    """

    per_pair: list[CodeSwitchScore]
    within_tolerance_count: int
    total: int
    eval_set_score: float
    passes: bool
    adaptation_hook: str | None


class HinglishDataEngine:
    """Deterministic Romanized↔Devanagari normalization for Hinglish text.

    The engine holds the transliteration mapping in both directions as instance
    attributes so the *same* table backs input normalization (Romanized →
    Devanagari) and output rendering (Devanagari → Romanized):

    - ``self._roman_to_deva``: Romanized token → Devanagari token.
    - ``self._deva_to_roman``: Devanagari token → canonical Romanized token
      (first Romanized spelling seen for each Devanagari form).

    :meth:`normalize` canonicalizes input to Devanagari: a recognized Romanized
    token is replaced by its Devanagari form, a token that is *already* a
    recognized Devanagari form is passed through unchanged (it is "mapped", so it
    is not flagged), and any token absent from the mapping is retained unchanged
    and reported as unmapped (Requirement 5.8).

    Determinism (Requirement 5.5) follows from the normalization being a pure,
    order-independent dictionary lookup per token with no randomness or mutable
    shared state: ``normalize(s)`` always returns the same result for the same
    ``s``.
    """

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        """Construct the engine from a Romanized → Devanagari mapping.

        Args:
            mapping: Optional Romanized → Devanagari table. When ``None`` the
                built-in :data:`DEFAULT_ROMANIZED_TO_DEVANAGARI` is used — that
                default is itself loaded from the versioned
                ``roadmap/data/hinglish_map.json`` at import time (Task 34.1). A
                copy is stored so the engine is insulated from later mutation of
                the caller's dict.
        """
        source = DEFAULT_ROMANIZED_TO_DEVANAGARI if mapping is None else mapping
        # Store a private copy so external mutation cannot change behaviour.
        self._roman_to_deva: dict[str, str] = dict(source)
        # Build the reverse map once. First Romanized spelling wins so the
        # rendering direction is deterministic even when several spellings share
        # one Devanagari form.
        reverse: dict[str, str] = {}
        for roman, deva in self._roman_to_deva.items():
            reverse.setdefault(deva, roman)
        self._deva_to_roman: dict[str, str] = reverse

    @property
    def mapping_size(self) -> int:
        """Number of Romanized → Devanagari entries in the loaded mapping."""
        return len(self._roman_to_deva)

    def normalize(self, text: str) -> NormalizationResult:
        """Normalize ``text`` to its canonical Devanagari form.

        Tokenizes ``text`` on whitespace (preserving the original spacing) and,
        for each token:

        - replaces a recognized Romanized token with its Devanagari form
          (input-normalization direction);
        - passes through a token that is already a recognized Devanagari form
          unchanged (it is part of the mapping, so it is *not* flagged);
        - otherwise retains the token unchanged in ``normalized_text`` and also
          appends it to ``unmapped_tokens`` for review (Requirement 5.8).

        The transformation is a pure per-token dictionary lookup, so the same
        input always yields the same output (Requirement 5.5).

        Args:
            text: The input string to normalize.

        Returns:
            A :class:`NormalizationResult` whose ``normalized_text`` is the
            rebuilt string and whose ``unmapped_tokens`` lists, in order of
            occurrence, every token that had no mapping entry.
        """
        if not isinstance(text, str):
            raise TypeError(f"text must be a str, got {type(text)!r}")

        unmapped_tokens: list[str] = []
        rendered_parts: list[str] = []

        for part in _WHITESPACE_SPLIT.split(text):
            # Whitespace runs (and the empty strings re.split can yield at the
            # ends) are preserved verbatim so spacing is reproduced exactly.
            if part == "" or part.isspace():
                rendered_parts.append(part)
                continue

            rendered_parts.append(self._normalize_token(part, unmapped_tokens))

        return NormalizationResult(
            normalized_text="".join(rendered_parts),
            unmapped_tokens=unmapped_tokens,
        )

    def _normalize_token(self, token: str, unmapped_tokens: list[str]) -> str:
        """Resolve a single non-whitespace token to its normalized form.

        Appends to ``unmapped_tokens`` (in place) when the token has no mapping
        entry. Returns the token's normalized rendering (its Devanagari form, or
        the unchanged original when it is already Devanagari or unmapped).
        """
        deva = self._roman_to_deva.get(token)
        if deva is not None:
            # Romanized token with an entry: normalize to Devanagari.
            return deva
        if token in self._deva_to_roman:
            # Already a recognized Devanagari form: canonical, retain unchanged.
            return token
        # No entry in either direction: retain unchanged and flag for review.
        unmapped_tokens.append(token)
        return token

    # ------------------------------------------------------------------
    # Code-switch quality scoring (Requirements 5.4, 5.6, 5.7)
    # ------------------------------------------------------------------

    def _classify_token(self, token: str) -> str | None:
        """Classify one token as ``"hindi"``, ``"english"`` or ``None``.

        A token is **Hindi** when it contains any Devanagari character or, after
        stripping edge punctuation and case-folding, it is a recognized
        Hinglish-Hindi token in the engine's mapping (a Romanized form with a
        Devanagari entry, or a known Devanagari form). A token is **English**
        when it carries a Latin letter and is not a recognized Hinglish-Hindi
        token. Tokens with neither Devanagari nor Latin letters (pure
        punctuation, digits, emoji, …) return ``None`` and are ignored by the
        ratio.
        """
        # Devanagari content is unambiguously Hindi, regardless of punctuation.
        if _DEVANAGARI_CHAR.search(token):
            return "hindi"

        core = token.strip(_EDGE_PUNCT)
        if not core:
            return None

        folded = core.casefold()
        # Recognized Romanized Hinglish-Hindi word (reuse the normalize mapping).
        if folded in self._roman_to_deva:
            return "hindi"

        # A Latin-script word that is not a known Hindi token is English.
        if _LATIN_CHAR.search(core):
            return "english"

        # Neither Devanagari nor Latin letters (digits/emoji/symbols): ignore.
        return None

    def he_ratio(self, text: str) -> float:
        """Return the Hindi-to-English (H/E) ratio of ``text`` as a percentage.

        The ratio is ``100 * hindi / (hindi + english)`` over the classifiable
        word tokens of ``text`` (see the module docstring for the definition).
        Text with no classifiable Hindi/English tokens has a ratio of ``0.0``.

        Args:
            text: The text whose H/E ratio is computed.

        Returns:
            The H/E ratio on a ``0.0..100.0`` percentage scale.
        """
        if not isinstance(text, str):
            raise TypeError(f"text must be a str, got {type(text)!r}")

        hindi = 0
        english = 0
        for token in text.split():
            kind = self._classify_token(token)
            if kind == "hindi":
                hindi += 1
            elif kind == "english":
                english += 1

        denominator = hindi + english
        if denominator == 0:
            return 0.0
        return 100.0 * hindi / denominator

    def score(self, input: str, output: str) -> CodeSwitchScore:
        """Score the code-switch quality of a single (input, output) pair.

        A response is **within tolerance** iff the absolute difference between
        its H/E ratio and the input's H/E ratio is at most 15 percentage points
        (Requirement 5.4). The returned :class:`CodeSwitchScore` carries the
        input ratio, the output ratio, the absolute difference in percentage
        points, the ``within_tolerance`` boolean, and a per-pair ``quality``
        percentage (``100.0`` within tolerance, ``0.0`` otherwise).

        Args:
            input: The code-switched user input text.
            output: The system response text.

        Returns:
            The structured :class:`CodeSwitchScore` for the pair.
        """
        input_ratio = self.he_ratio(input)
        output_ratio = self.he_ratio(output)
        difference_pp = abs(output_ratio - input_ratio)
        within_tolerance = difference_pp <= TOLERANCE_PP
        return CodeSwitchScore(
            input_ratio=input_ratio,
            output_ratio=output_ratio,
            difference_pp=difference_pp,
            within_tolerance=within_tolerance,
            quality=100.0 if within_tolerance else 0.0,
        )

    def within_tolerance(self, input: str, output: str) -> bool:
        """Return whether a single (input, output) pair is within tolerance.

        Convenience boolean wrapper over :meth:`score`: a response is **within
        tolerance** iff the absolute difference between its H/E ratio and the
        input's H/E ratio is at most :data:`TOLERANCE_PCT` (15) percentage points
        (Requirement 5.4). Equivalent to ``self.score(input, output)
        .within_tolerance`` but returned directly as a ``bool`` for callers that
        only need the pass/fail decision.

        Args:
            input: The code-switched user input text.
            output: The system response text.

        Returns:
            ``True`` iff ``|output H/E ratio - input H/E ratio| <= 15`` pp.
        """
        return self.score(input, output).within_tolerance

    @staticmethod
    def benchmark_passes(eval_set_score: float) -> bool:
        """Return whether an evaluation-set score passes the Hinglish benchmark.

        A build passes iff the evaluation-set score is at or above the 80%
        threshold (Requirement 5.6). When this returns ``False``, the roadmap's
        remediation is lightweight adaptation (LoRA/adapters) on the
        Hinglish_Data_Engine output before any custom-model work (Requirement
        5.7); see :data:`LORA_ADAPTATION_HOOK`.

        Args:
            eval_set_score: The evaluation-set score as a percentage
                (``0.0..100.0``).

        Returns:
            ``True`` iff ``eval_set_score >= 80.0``.
        """
        return eval_set_score >= BENCHMARK_PASS_THRESHOLD

    def evaluate_benchmark(
        self, pairs: Iterable[tuple[str, str]]
    ) -> BenchmarkResult:
        """Aggregate per-pair code-switch results into a benchmark result.

        Each ``(input, output)`` pair is scored with :meth:`score`; the
        evaluation-set score is the percentage of pairs within tolerance, and
        the build passes iff that score is ``>= 80%`` (Requirement 5.6). When
        the build does not pass, ``adaptation_hook`` names the
        lightweight-adaptation (LoRA/adapters) remediation applied before any
        custom-model work (Requirement 5.7).

        Args:
            pairs: An iterable of ``(input, output)`` text pairs.

        Returns:
            A :class:`BenchmarkResult` with the per-pair scores, the
            within-tolerance count, the total, the evaluation-set percentage,
            the pass flag, and the adaptation hook (``None`` when passing).
        """
        per_pair = [self.score(inp, out) for inp, out in pairs]
        total = len(per_pair)
        within_tolerance_count = sum(1 for s in per_pair if s.within_tolerance)
        # An empty evaluation set scores 0.0 and therefore does not pass.
        eval_set_score = (
            100.0 * within_tolerance_count / total if total else 0.0
        )
        passes = self.benchmark_passes(eval_set_score)
        return BenchmarkResult(
            per_pair=per_pair,
            within_tolerance_count=within_tolerance_count,
            total=total,
            eval_set_score=eval_set_score,
            passes=passes,
            adaptation_hook=None if passes else LORA_ADAPTATION_HOOK,
        )
