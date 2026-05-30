"""
evals/hinglish/scorer.py — code-switch + transliteration scoring (final_use.md §12).
====================================================================================
Deterministic, fixture-based scoring for the Hinglish / code-switch evaluation
dimension ("Hinglish fluency and transliteration robustness — own data moat
matters", final_use.md §12).

Two real signals are computed here, both pure-Python / stdlib (no models):

  * **code-switch ratio** — how often the language flips between adjacent word
    tokens. A monolingual utterance scores 0.0; a perfectly alternating
    bilingual utterance scores 1.0. This is a measurable property of an
    utterance, not a learned judgement.
  * **transliteration robustness** — how close a produced romanization is to a
    reference romanization, measured as ``1 - CER`` (character error rate from
    ``evals.text_metrics``). Robust transliteration → score near 1.0.

Language of a token is classified with a small, explicit lexicon + Devanagari
script detection. This is deliberately simple and auditable: the goal is a
*stable, reproducible* metric over fixtures, not a production language ID model.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.text_metrics import character_error_rate, is_devanagari, tokenize

__all__ = [
    "ROMANIZED_HINDI_LEXICON",
    "classify_token",
    "language_profile",
    "code_switch_ratio",
    "transliteration_robustness",
    "CodeSwitchSample",
    "score_code_switch",
    "score_samples",
    "load_samples",
]


# A small, explicit lexicon of common romanized Hindi tokens. Tokens not found
# here and not in Devanagari script are treated as English. Kept intentionally
# auditable; extend via fixtures rather than guessing.
ROMANIZED_HINDI_LEXICON: frozenset[str] = frozenset(
    {
        "namaste", "namaskar", "haan", "haa", "nahi", "nahin", "yaar", "bhai",
        "dost", "aap", "tum", "main", "mai", "hum", "mujhe", "tujhe", "humein",
        "hai", "hain", "ho", "hoon", "tha", "thi", "the", "kya", "kyun", "kyon",
        "kaise", "kaisa", "kaisi", "kab", "kahan", "kaun", "kal", "aaj", "abhi",
        "ka", "ki", "ke", "ko", "se", "me", "mein", "par", "aur", "lekin",
        "thik", "theek", "accha", "achha", "bahut", "thoda", "thodi", "jaldi",
        "karna", "karo", "kar", "raha", "rahi", "rahe", "lag", "laga",
        "lagi", "sab", "kuch", "kuchh", "mushkil", "asaan", "please", "shukriya",
        "dhanyavaad", "matlab", "chalo", "ruko", "suno", "dekho", "samajh",
        "plan", "banana", "chahiye", "milega", "batao", "bata",
    }
)
# Tokens that are ambiguous (valid as both a romanized-Hindi word and a common
# English word) — excluded from the effective Hindi set so they do not bias the
# classifier toward Hindi. e.g. "the" (English article vs romanized थे), "main"
# (English adjective vs मैं), "plan"/"banana"/"me". Keeping these English-leaning
# makes the code-switch metric stable and reproducible over fixtures.
_AMBIGUOUS: frozenset[str] = frozenset({"plan", "banana", "me", "the", "main"})
_EFFECTIVE_HINDI = ROMANIZED_HINDI_LEXICON - _AMBIGUOUS


def classify_token(token: str) -> str:
    """Classify a single word token as ``"hi"`` (Hindi) or ``"en"`` (English).

    Rules (in order):
      1. Any Devanagari character → Hindi.
      2. Token in the romanized-Hindi lexicon → Hindi.
      3. Otherwise → English.
    """
    if is_devanagari(token):
        return "hi"
    if token.casefold() in _EFFECTIVE_HINDI:
        return "hi"
    return "en"


def language_profile(text: str) -> dict[str, float | int]:
    """Return token counts + language fractions for ``text``.

    Keys: ``tokens`` (int), ``hi`` (int), ``en`` (int), ``hi_fraction`` (float),
    ``en_fraction`` (float).
    """
    tokens = tokenize(text)
    if not tokens:
        return {"tokens": 0, "hi": 0, "en": 0, "hi_fraction": 0.0, "en_fraction": 0.0}
    labels = [classify_token(t) for t in tokens]
    hi = labels.count("hi")
    en = labels.count("en")
    n = len(tokens)
    return {
        "tokens": n,
        "hi": hi,
        "en": en,
        "hi_fraction": hi / n,
        "en_fraction": en / n,
    }


def code_switch_ratio(text: str) -> float:
    """Fraction of adjacent token-pairs whose language differs.

    Returns a value in [0, 1]:
      * 0.0 for a monolingual utterance (or fewer than 2 tokens),
      * 1.0 for a perfectly alternating bilingual utterance.
    """
    tokens = tokenize(text)
    if len(tokens) < 2:
        return 0.0
    labels = [classify_token(t) for t in tokens]
    switches = sum(1 for a, b in zip(labels, labels[1:], strict=False) if a != b)
    return switches / (len(labels) - 1)


def transliteration_robustness(hypothesis: str, reference: str) -> float:
    """Transliteration robustness = ``1 - CER(hypothesis, reference)``, clamped [0, 1].

    Identical strings → 1.0. Heavier character-level divergence → lower score.
    """
    cer = character_error_rate(reference, hypothesis)
    return max(0.0, min(1.0, 1.0 - cer))


@dataclass
class CodeSwitchSample:
    """One Hinglish evaluation sample.

    ``text`` is the produced/observed utterance. ``reference_translit`` (optional)
    is a reference romanization for transliteration-robustness scoring. When the
    sample is expected to be code-switched, ``expect_code_switch`` is True.
    """

    text: str
    reference_translit: str | None = None
    expect_code_switch: bool = True


def score_code_switch(sample: CodeSwitchSample) -> float:
    """Combined Hinglish dimension score in [0, 1] for one sample.

    The score rewards two things:
      * **code-switch presence** matching expectation — a Hinglish sample that
        actually mixes languages scores well; a monolingual one that was
        expected to code-switch is penalised (and vice-versa).
      * **transliteration robustness** when a reference romanization is given.

    With no reference romanization the score is the code-switch component alone.
    """
    profile = language_profile(sample.text)
    has_both = bool(profile["hi"]) and bool(profile["en"])
    if sample.expect_code_switch:
        cs_component = 1.0 if has_both else 0.0
    else:
        cs_component = 0.0 if has_both else 1.0

    if sample.reference_translit is None:
        return cs_component
    translit = transliteration_robustness(sample.text, sample.reference_translit)
    # Weight: presence of correct mixing matters slightly more than exact spelling.
    return 0.6 * cs_component + 0.4 * translit


def score_samples(samples: list[CodeSwitchSample]) -> float:
    """Mean code-switch dimension score across ``samples`` (1.0 if empty)."""
    if not samples:
        return 1.0
    return sum(score_code_switch(s) for s in samples) / len(samples)


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------
def load_samples(path: str | None = None) -> list[CodeSwitchSample]:
    """Load :class:`CodeSwitchSample` fixtures from a JSON file.

    Defaults to the bundled ``evals/hinglish/fixtures.json``.
    """
    import json
    from pathlib import Path

    p = Path(path) if path is not None else Path(__file__).parent / "fixtures.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return [
        CodeSwitchSample(
            text=s["text"],
            reference_translit=s.get("reference_translit"),
            expect_code_switch=s.get("expect_code_switch", True),
        )
        for s in data.get("samples", [])
    ]
