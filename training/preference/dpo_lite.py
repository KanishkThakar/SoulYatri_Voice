"""
training/preference/dpo_lite.py — Phase 14B DPO-lite preference optimization scaffolding.

DPO-lite (Direct Preference Optimization, lightweight) preference optimization, applied
*after* initial SFT (final_use.md §11.1 addendum A). Operates on ``PreferenceRecord``s
(prompt + chosen + rejected) with full provenance + consent.

Same constraints as ``lora_sft.py``:
  * imports cleanly on CPU — no top-level torch/trl/transformers import;
  * exposes ``--dry-run`` validating inputs (config, preference data, consent) WITHOUT
    training;
  * gated by a measurable product gain (no-scratch-training discipline);
  * records a reproducible run manifest (config, seed, data hash, metrics).

Running without ``--dry-run`` raises ``TrainingUnavailableError`` on this CPU/no-GPU host.
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
    "DPOLiteConfig",
    "TrainingUnavailableError",
    "GatingError",
    "load_preference_dataset",
    "dry_run",
    "run",
    "build_arg_parser",
    "main",
]

log = get_logger("training.preference.dpo_lite")

# DPO-lite is applied to generative/response targets only.
SUPPORTED_TARGETS = ("aux_text_brain", "filler_router", "main_runtime")


class TrainingUnavailableError(RuntimeError):
    """Raised when an actual DPO run is requested but no GPU/training deps exist."""


class GatingError(ValueError):
    """Raised when preference optimization is not justified by a measurable product gain."""


@dataclass
class DPOLiteConfig:
    """Reproducible DPO-lite hyperparameters + gating policy."""

    target: str = "aux_text_brain"
    base_model: str = "pending-human-pin"  # see docs/MODEL_LOCKS.md (post-SFT checkpoint)
    sft_checkpoint: str = "pending-sft"
    seed: int = 1234
    beta: float = 0.1  # DPO temperature / KL strength
    learning_rate: float = 5e-6
    epochs: int = 1
    batch_size: int = 4
    max_seq_len: int = 512
    # Measurable-gain gate (e.g. human preference win-rate over the SFT baseline).
    baseline_metric: float = 0.0
    candidate_metric: float = 0.0
    min_product_gain: float = 0.02
    metric_name: str = "preference_win_rate"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.target not in SUPPORTED_TARGETS:
            raise ValueError(
                f"unsupported target {self.target!r}; choose one of {SUPPORTED_TARGETS}"
            )
        if not 0.0 < self.beta <= 1.0:
            raise ValueError("beta must be in (0, 1]")
        if self.epochs <= 0:
            raise ValueError("epochs must be > 0")
        if self.min_product_gain < 0:
            raise ValueError("min_product_gain must be >= 0")

    @property
    def measured_gain(self) -> float:
        return self.candidate_metric - self.baseline_metric

    def gate_ok(self) -> bool:
        return self.measured_gain >= self.min_product_gain


# ---------------------------------------------------------------------------
# Data loading + validation
# ---------------------------------------------------------------------------
def load_preference_dataset(path: str | Path) -> list[dict]:
    """Load a JSONL preference dataset into a list of raw dicts."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"preference dataset not found: {p}")
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


def _validate_preferences(items: list[dict]) -> tuple[list, list[dict]]:
    """Validate preference records: schema (provenance/consent), kind, consent-eligibility."""
    valid, rejected = validate_records(items)
    eligible = []
    for rec in valid:
        if rec.kind != DataKind.preference:
            rejected.append(
                {"sample_id": rec.sample_id, "error": f"kind {rec.kind.value} != preference"}
            )
            continue
        if not rec.is_training_eligible:
            rejected.append(
                {
                    "sample_id": rec.sample_id,
                    "error": f"consent {rec.consent.status.value} not eligible",
                }
            )
            continue
        eligible.append(rec)
    return eligible, rejected


# ---------------------------------------------------------------------------
# Dry-run + run
# ---------------------------------------------------------------------------
def dry_run(
    config: DPOLiteConfig, dataset_path: str | Path, runs_dir: str | Path | None = None
) -> RunManifest:
    """Validate config + preference dataset and emit a manifest WITHOUT training."""
    items = load_preference_dataset(dataset_path)
    eligible, rejected = _validate_preferences(items)

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
        run_id=f"dpo_lite-{config.target}-seed{config.seed}-dryrun",
        method="dpo_lite",
        target=config.target,
        seed=config.seed,
        config=asdict(config),
        data_hash=data_hash_for([r.model_dump(mode="json") for r in eligible]),
        record_count=len(eligible),
        metrics=metrics,
        executed=False,
        notes=(
            f"DRY-RUN: validated {len(eligible)} eligible / {len(items)} total preference pairs "
            f"({len(rejected)} rejected). Gate {'PASS' if gate_ok else 'BLOCK'} "
            f"(measured gain {config.measured_gain:+.4f} vs min {config.min_product_gain:.4f}). "
            "Applied after SFT. No training executed (CPU/no-weights)."
        ),
    )

    log.info(
        "dpo_dry_run",
        target=config.target,
        records_total=len(items),
        records_eligible=len(eligible),
        records_rejected=len(rejected),
        gate_ok=gate_ok,
        measured_gain=config.measured_gain,
    )
    if rejected:
        log.warning("dpo_dry_run_rejections", count=len(rejected), sample=rejected[:3])

    if runs_dir is not None:
        out = manifest.write(Path(runs_dir) / manifest.run_id)
        log.info("dpo_manifest_written", path=str(out))

    return manifest


def run(
    config: DPOLiteConfig, dataset_path: str | Path, runs_dir: str | Path | None = None
) -> RunManifest:
    """Execute an actual DPO-lite run. Not available on CPU/no-weights environments."""
    dry_run(config, dataset_path, runs_dir=None)
    if not config.gate_ok():
        raise GatingError(
            f"preference optimization blocked: measured gain {config.measured_gain:+.4f} < "
            f"min_product_gain {config.min_product_gain:.4f} (no-scratch-training rule)"
        )
    try:
        import torch  # noqa: F401, PLC0415
        from transformers import AutoModelForCausalLM  # noqa: F401, PLC0415
        from trl import DPOTrainer  # noqa: F401, PLC0415
    except Exception as exc:  # pragma: no cover - no GPU stack in this environment
        raise TrainingUnavailableError(
            "actual DPO-lite training requires torch + transformers + trl and a GPU; "
            "not available in this environment. Use --dry-run, or run on a GPU host. "
            f"(import error: {exc})"
        ) from exc

    raise TrainingUnavailableError(  # pragma: no cover
        "DPO training execution is intentionally not implemented in this scaffolding; "
        "a GPU host should wire DPOTrainer here using the recorded manifest."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dpo_lite",
        description="DPO-lite preference optimization scaffolding for SoulYatri (Phase 14B).",
    )
    p.add_argument("--target", choices=SUPPORTED_TARGETS, default="aux_text_brain")
    p.add_argument("--dataset", required=True, help="Path to a JSONL preference dataset.")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--base-model", default="pending-human-pin")
    p.add_argument("--sft-checkpoint", default="pending-sft")
    p.add_argument("--beta", type=float, default=0.1)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--baseline-metric", type=float, default=0.0)
    p.add_argument("--candidate-metric", type=float, default=0.0)
    p.add_argument("--min-product-gain", type=float, default=0.02)
    p.add_argument("--runs-dir", default=None, help="Optional dir to write the run manifest note.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config + preference data (provenance/consent) without training.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = DPOLiteConfig(
        target=args.target,
        base_model=args.base_model,
        sft_checkpoint=args.sft_checkpoint,
        seed=args.seed,
        beta=args.beta,
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
        log.error("dpo_run_blocked", error=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
