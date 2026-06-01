"""
training/data_engine/synthetic.py — Phase 14C synthetic Hinglish prompt engine.

Produces Romanized ↔ native-script (Devanagari) Hinglish pairs as ``HinglishPairRecord``s
with full provenance (``source_type=synthetic``) and consent (``not_applicable`` — no human
subject). The engine is:

  * **deterministic / reproducible** — seeded by an integer; the same ``seed`` + ``count``
    yields the same records (so a GPU machine reproduces the corpus exactly);
  * **filtered** — a quality filter drops degenerate/duplicate pairs before they leave the
    engine (``generate`` returns only records that pass);
  * **reviewable + measurable** — every record is marked ``reviewed=False`` so the labeling
    workflow (``training/labeling/review.py``) gates it, and the engine exposes a
    deterministic split so synthetic data can be measured against a human-eval set.

No GPU / torch / transformers — pure stdlib + the local schema. Imports cleanly on CPU.

Design note: this is a *template-composition* generator, not a model. It does not invent
language; it combines a curated, reviewable bank of Hinglish fragments. That keeps the
synthetic corpus auditable and human-curatable, per final_use.md §11.2 / §13.2.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .logging_util import get_logger
from .schema import (
    Consent,
    ConsentStatus,
    DataSplit,
    HinglishPairRecord,
    Language,
    Provenance,
    SourceType,
)

__all__ = [
    "HinglishTemplate",
    "SyntheticConfig",
    "SyntheticHinglishEngine",
    "DEFAULT_TEMPLATES",
]

log = get_logger("training.data_engine.synthetic")


# ---------------------------------------------------------------------------
# Curated, reviewable fragment bank
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HinglishTemplate:
    """A single curated Hinglish line with both scripts and turn metadata.

    Kept as a flat record (not a string-format template) so each line is human-reviewable
    and the Romanized/native mapping is explicit rather than machine-transliterated.
    """

    romanized: str
    native: str
    intent: str
    emotion: str


# A small, intentionally curated seed bank. Real deployments extend this from reviewed,
# consented material; it stays small here so the corpus is auditable and tests are stable.
DEFAULT_TEMPLATES: tuple[HinglishTemplate, ...] = (
    HinglishTemplate("namaste, kaise ho aap?", "नमस्ते, कैसे हो आप?", "greeting", "warm_ack"),
    HinglishTemplate(
        "haan bilkul, main sun raha hoon", "हाँ बिल्कुल, मैं सुन रहा हूँ", "acknowledgment", "warm_ack"
    ),
    HinglishTemplate(
        "ek minute ruko, main check karta hoon", "एक मिनट रुको, मैं चेक करता हूँ", "hold", "neutral"
    ),
    HinglishTemplate(
        "koi baat nahi, sab theek ho jayega", "कोई बात नहीं, सब ठीक हो जाएगा", "reassurance", "calm"
    ),
    HinglishTemplate("arre wah, yeh to badhiya hai", "अरे वाह, यह तो बढ़िया है", "delight", "excited"),
    HinglishTemplate(
        "mujhe samajh aa gaya, dhanyavaad", "मुझे समझ आ गया, धन्यवाद", "confirmation", "warm_ack"
    ),
    HinglishTemplate("thoda dheere bolo please", "थोड़ा धीरे बोलो प्लीज़", "request", "neutral"),
    HinglishTemplate("main yahin hoon, ghabrao mat", "मैं यहीं हूँ, घबराओ मत", "reassurance", "calm"),
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass
class SyntheticConfig:
    """Reproducible configuration for a synthetic generation run."""

    seed: int = 1234
    count: int = 8
    pipeline_version: str = "synthetic_v1"
    source_id: str = "synthetic_v1"
    split: DataSplit = DataSplit.train
    # Fraction routed to the held-out human-eval split (measurable against human eval).
    human_eval_fraction: float = 0.25
    templates: tuple[HinglishTemplate, ...] = field(default_factory=lambda: DEFAULT_TEMPLATES)

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("count must be >= 0")
        if not 0.0 <= self.human_eval_fraction <= 1.0:
            raise ValueError("human_eval_fraction must be in [0, 1]")
        if not self.templates:
            raise ValueError("templates bank must not be empty")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class SyntheticHinglishEngine:
    """Deterministic synthetic Hinglish pair generator.

    Given a ``SyntheticConfig`` (seed + count), produces a reproducible list of validated,
    filtered ``HinglishPairRecord``s. Same seed + count ⇒ identical output.
    """

    def __init__(self, config: SyntheticConfig | None = None) -> None:
        self.config = config or SyntheticConfig()

    # -- provenance / consent for synthetic data -----------------------------
    def _provenance(self, idx: int) -> Provenance:
        return Provenance(
            source_type=SourceType.synthetic,
            source_id=self.config.source_id,
            pipeline_version=self.config.pipeline_version,
            notes=f"synthetic Hinglish pair #{idx}",
        )

    @staticmethod
    def _consent() -> Consent:
        # Synthetic data has no human subject → consent is not applicable ("n/a").
        return Consent(status=ConsentStatus.not_applicable, can_train=True)

    # -- quality filter ------------------------------------------------------
    @staticmethod
    def _passes_filter(romanized: str, native: str, seen: set[str]) -> bool:
        """Drop degenerate or duplicate pairs.

        Rejects: blank sides, identical scripts (no actual transliteration), and exact
        duplicates within a run. This is the 'synthetic data is filtered' guarantee.
        """
        r = romanized.strip()
        n = native.strip()
        if not r or not n:
            return False
        if r == n:
            return False
        key = f"{r}\u241f{n}"
        if key in seen:
            return False
        seen.add(key)
        return True

    # -- split assignment (deterministic) ------------------------------------
    def _assign_split(self, rng: random.Random) -> DataSplit:
        """Route a deterministic fraction of records to a held-out human-eval (test) split."""
        if rng.random() < self.config.human_eval_fraction:
            return DataSplit.test
        return self.config.split

    # -- generation ----------------------------------------------------------
    def generate(self) -> list[HinglishPairRecord]:
        """Generate the configured number of filtered, validated Hinglish pairs.

        Deterministic: the per-record RNG is derived from ``seed`` + index, so the result is
        stable and independent of iteration-order side effects.
        """
        cfg = self.config
        records: list[HinglishPairRecord] = []
        seen: set[str] = set()
        templates = cfg.templates
        n_templates = len(templates)

        idx = 0
        attempts = 0
        max_attempts = max(cfg.count * 8, n_templates * 8, 1)
        while len(records) < cfg.count and attempts < max_attempts:
            # Deterministic per-slot RNG: stable regardless of how many were filtered.
            rng = random.Random(f"{cfg.seed}:{idx}")
            template = templates[rng.randrange(n_templates)]
            # Optional deterministic variation: occasionally append a soft closer.
            closer_roman, closer_native = rng.choice(
                [("", ""), (" theek hai?", " ठीक है?"), (" haan", " हाँ")]
            )
            romanized = (template.romanized + closer_roman).strip()
            native = (template.native + closer_native).strip()

            if self._passes_filter(romanized, native, seen):
                split = self._assign_split(random.Random(f"{cfg.seed}:split:{idx}"))
                record = HinglishPairRecord(
                    sample_id=f"{cfg.source_id}:{cfg.seed}:{idx:04d}",
                    lang=Language.hinglish,
                    split=split,
                    provenance=self._provenance(idx),
                    consent=self._consent(),
                    romanized_text=romanized,
                    native_text=native,
                    intent=template.intent,
                    emotion=template.emotion,
                    reviewed=False,  # must pass human review before training use
                    tags=["synthetic", "hinglish", "code_switch"],
                )
                records.append(record)
                idx += 1
            else:
                idx += 1
            attempts += 1

        log.info(
            "synthetic_generation_complete",
            seed=cfg.seed,
            requested=cfg.count,
            produced=len(records),
            filtered_out=attempts - len(records),
            templates=n_templates,
        )
        return records

    def generate_dicts(self) -> list[dict]:
        """Generate records as JSON-ready dicts (for JSONL export / dry-run validation)."""
        return [r.model_dump(mode="json") for r in self.generate()]
