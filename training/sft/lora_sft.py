"""
training/sft/lora_sft.py — Phase 14B SFT/LoRA adaptation scaffolding.

Reproducible, metric-recording SFT/LoRA adaptation scripts for the auxiliary targets the
guide allows fine-tuning (final_use.md §13.3 priority order):

  1. ``aux_stt``         — auxiliary STT if Hinglish accuracy is weak
  2. ``emotion_encoder`` — emotion encoder if affect detection is unstable
  3. ``filler_router``   — filler selector/router if latency masking is poor
  4. ``main_runtime``    — Moshi adapters ONLY after baseline quality + latency are proven

**Hard constraints for this environment (CPU-only, no GPU/weights):**
  * imports cleanly on CPU — no top-level torch/transformers/peft import;
  * exposes ``--dry-run`` that validates inputs (config, data, consent) WITHOUT training;
  * respects the no-scratch-training rule — adaptation is gated by a measurable
    ``min_product_gain`` threshold recorded in the manifest;
  * records a reproducible run manifest (config, seed, data hash, metrics) under a
    ``runs/``-style note.

Running without ``--dry-run`` on a machine without a GPU/training deps raises a clear
``TrainingUnavailableError`` instead of pretending to train.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from training.data_engine.logging_util import get_logger
from training.data_engine.manifest import RunManifest, data_hash_for
from training.data_engine.schema import DataKind, validate_records

__all__ = [
    "SUPPORTED_TARGETS",
    "TARGET_EXPECTED_KINDS",
    "LoraSFTConfig",
    "TrainingUnavailableError",
    "GatingError",
    "load_dataset",
    "dry_run",
    "run",
    "build_arg_parser",
    "main",
]

log = get_logger("training.sft.lora_sft")

# Targets the guide permits adapting, in priority order (final_use.md §13.3).
SUPPORTED_TARGETS = ("aux_stt", "emotion_encoder", "filler_router", "main_runtime")

# Which dataset kind each target expects (used by dry-run validation).
TARGET_EXPECTED_KINDS: dict[str, DataKind] = {
    "aux_stt": DataKind.asr,
    "emotion_encoder": DataKind.emotion,
    "filler_router": DataKind.hinglish_pair,
    "main_runtime": DataKind.hinglish_pair,
}


class TrainingUnavailableError(RuntimeError):
    """Raised when an actual training run is requested but no GPU/training deps exist."""


class GatingError(ValueError):
    """Raised when adaptation is not justified by a measurable product gain."""


@dataclass
class LoraSFTConfig:
    """Reproducible SFT/LoRA hyperparameters + gating policy.

    These are recorded verbatim in the run manifest so a GPU host reproduces the run.
    """

    target: str = "aux_stt"
    base_model: str = "pending-human-pin"  # see docs/MODEL_LOCKS.md
    seed: int = 1234
    # LoRA hyperparameters
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    learning_rate: float = 1e-4
    epochs: int = 1
    batch_size: int = 8
    max_seq_len: int = 512
    # No-scratch-training gate: adaptation must clear a measurable product gain.
    baseline_metric: float = 0.0
    candidate_metric: float = 0.0
    min_product_gain: float = 0.01
    metric_name: str = "eval_score"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.target not in SUPPORTED_TARGETS:
            raise ValueError(
                f"unsupported target {self.target!r}; choose one of {SUPPORTED_TARGETS}"
            )
        if self.lora_rank <= 0:
            raise ValueError("lora_rank must be > 0")
        if self.epochs <= 0:
            raise ValueError("epochs must be > 0")
        if self.min_product_gain < 0:
            raise ValueError("min_product_gain must be >= 0")

    @property
    def measured_gain(self) -> float:
        return self.candidate_metric - self.baseline_metric

    def gate_ok(self) -> bool:
        """True if the measured product gain justifies adaptation."""
        return self.measured_gain >= self.min_product_gain


# ---------------------------------------------------------------------------
# Data loading + validation
# ---------------------------------------------------------------------------
def load_dataset(path: str | Path) -> list[dict]:
    """Load a JSONL dataset into a list of raw dicts (no schema coercion yet)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"dataset not found: {p}")
    items: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{lineno}: invalid JSON: {exc}") from exc
    return items


def _validate_dataset(items: list[dict], expected_kind: DataKind) -> tuple[list, list[dict]]:
    """Validate records against the schema (enforces provenance + consent).

    Also filters to (a) the expected kind for the target and (b) training-eligible consent.
    Returns ``(eligible_records, rejected)``.
    """
    valid, rejected = validate_records(items)
    eligible = []
    for rec in valid:
        if rec.kind != expected_kind:
            rejected.append(
                {
                    "sample_id": rec.sample_id,
                    "error": f"kind {rec.kind.value} != expected {expected_kind.value}",
                }
            )
            continue
        if not rec.is_training_eligible:
            rejected.append(
                {
                    "sample_id": rec.sample_id,
                    "error": f"consent {rec.consent.status.value} not training-eligible",
                }
            )
            continue
        eligible.append(rec)
    return eligible, rejected


# ---------------------------------------------------------------------------
# Dry-run + run
# ---------------------------------------------------------------------------
def dry_run(
    config: LoraSFTConfig, dataset_path: str | Path, runs_dir: str | Path | None = None
) -> RunManifest:
    """Validate config + dataset and emit a manifest WITHOUT training.

    Steps:
      1. load JSONL dataset,
      2. validate every record (rejects missing provenance/consent),
      3. filter to expected kind + training-eligible consent,
      4. check the measurable-gain gate,
      5. build a ``RunManifest`` (executed=False) and optionally write a runs note.
    """
    expected_kind = TARGET_EXPECTED_KINDS[config.target]
    items = load_dataset(dataset_path)
    eligible, rejected = _validate_dataset(items, expected_kind)

    gate_ok = config.gate_ok()
    metrics = {
        "records_total": float(len(items)),
        "records_eligible": float(len(eligible)),
        "records_rejected": float(len(rejected)),
        "baseline_metric": config.baseline_metric,
        "candidate_metric": config.candidate_metric,
        "measured_gain": config.measured_gain,
        "min_product_gain": config.min_product_gain,
        "gate_ok": 1.0 if gate_ok else 0.0,
    }

    manifest = RunManifest(
        run_id=f"sft_lora-{config.target}-seed{config.seed}-dryrun",
        method="sft_lora",
        target=config.target,
        seed=config.seed,
        config=asdict(config),
        data_hash=data_hash_for([r.model_dump(mode="json") for r in eligible]),
        record_count=len(eligible),
        metrics=metrics,
        executed=False,
        notes=(
            f"DRY-RUN: validated {len(eligible)} eligible / {len(items)} total records "
            f"({len(rejected)} rejected). Gate {'PASS' if gate_ok else 'BLOCK'} "
            f"(measured gain {config.measured_gain:+.4f} vs min {config.min_product_gain:.4f}). "
            "No training executed (CPU/no-weights)."
        ),
    )

    log.info(
        "sft_dry_run",
        target=config.target,
        records_total=len(items),
        records_eligible=len(eligible),
        records_rejected=len(rejected),
        gate_ok=gate_ok,
        measured_gain=config.measured_gain,
    )
    if rejected:
        log.warning("sft_dry_run_rejections", count=len(rejected), sample=rejected[:3])

    if runs_dir is not None:
        out = manifest.write(Path(runs_dir) / manifest.run_id)
        log.info("sft_manifest_written", path=str(out))

    return manifest


def run(
    config: LoraSFTConfig, dataset_path: str | Path, runs_dir: str | Path | None = None
) -> RunManifest:
    """Execute an actual SFT/LoRA run. Not available on CPU/no-weights environments.

    Always validates inputs first (via ``dry_run``); then enforces the gating policy; then
    attempts to import the heavy training stack. On this environment that import is absent,
    so it raises ``TrainingUnavailableError`` rather than faking a run.
    """
    dry_run(config, dataset_path, runs_dir=None)
    if not config.gate_ok():
        raise GatingError(
            f"adaptation blocked: measured gain {config.measured_gain:+.4f} < "
            f"min_product_gain {config.min_product_gain:.4f} (no-scratch-training rule)"
        )
    # Lazy import — never at module top level (keeps CPU import clean).
    try:
        import torch  # noqa: F401, PLC0415
        from peft import LoraConfig  # noqa: F401, PLC0415
        from transformers import Trainer  # noqa: F401, PLC0415
    except Exception as exc:  # pragma: no cover - no GPU stack in this environment
        raise TrainingUnavailableError(
            "actual SFT/LoRA training requires torch + transformers + peft and a GPU; "
            "not available in this environment. Use --dry-run, or run on a GPU host. "
            f"(import error: {exc})"
        ) from exc

    # pragma: no cover below — only reachable on a fully-provisioned GPU host.
    raise TrainingUnavailableError(  # pragma: no cover
        "training execution is intentionally not implemented in this scaffolding; "
        "a GPU host should wire the Trainer here using the recorded manifest."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lora_sft",
        description="SFT/LoRA adaptation scaffolding for SoulYatri auxiliary models (Phase 14B).",
    )
    p.add_argument("--target", choices=SUPPORTED_TARGETS, default="aux_stt")
    p.add_argument("--dataset", required=True, help="Path to a JSONL dataset.")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--base-model", default="pending-human-pin")
    p.add_argument("--lora-rank", type=int, default=16)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--baseline-metric", type=float, default=0.0)
    p.add_argument("--candidate-metric", type=float, default=0.0)
    p.add_argument("--min-product-gain", type=float, default=0.01)
    p.add_argument("--runs-dir", default=None, help="Optional dir to write the run manifest note.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config + dataset (provenance/consent) without training.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = LoraSFTConfig(
        target=args.target,
        base_model=args.base_model,
        seed=args.seed,
        lora_rank=args.lora_rank,
        epochs=args.epochs,
        baseline_metric=args.baseline_metric,
        candidate_metric=args.candidate_metric,
        min_product_gain=args.min_product_gain,
    )
    if args.dry_run:
        manifest = dry_run(config, args.dataset, runs_dir=args.runs_dir)
        print(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    try:
        run(config, args.dataset, runs_dir=args.runs_dir)
    except (TrainingUnavailableError, GatingError) as exc:
        log.error("sft_run_blocked", error=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
