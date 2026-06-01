"""
training/data_engine/manifest.py — reproducible run manifests for adaptation scripts.

Both ``training/sft/lora_sft.py`` and ``training/preference/dpo_lite.py`` must record a
run manifest (config, seed, data hash, metrics) so a GPU machine can reproduce the run and
so acceptance evidence lands under a ``runs/``-style note (final_use.md §3.3, §14B).

This module does NOT run training. It only builds and serializes the manifest object.

CPU/no-weights rule: pure stdlib + pydantic. Imports cleanly on CPU.
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["RunManifest", "data_hash_for", "utc_now_iso"]


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def data_hash_for(items: list[dict[str, Any]] | list[str] | str) -> str:
    """Deterministic SHA-256 over a dataset description.

    Accepts a list of record dicts, a list of file paths, or a single path string. For
    record dicts the canonical JSON is hashed; for paths the path strings are hashed (the
    files themselves are not read, keeping this CPU/no-IO friendly for dry runs).
    """
    if isinstance(items, str):
        payload = items
    elif items and isinstance(items[0], dict):
        payload = json.dumps(items, sort_keys=True, ensure_ascii=False, default=str)
    else:
        payload = "\n".join(sorted(str(x) for x in items))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RunManifest(BaseModel):
    """A reproducible record of an adaptation run (or a dry-run validation).

    Captures everything needed to reproduce the run on a GPU host: method, target, seed,
    config, data hash, and (post-run) metrics. ``executed=False`` marks a dry-run that
    validated inputs without training.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    method: str = Field(description="e.g. 'sft_lora', 'dpo_lite'.")
    target: str = Field(description="Adaptation target, e.g. 'aux_stt', 'emotion_encoder'.")
    seed: int
    created_ts: str = Field(default_factory=utc_now_iso)
    config: dict[str, Any] = Field(default_factory=dict)
    data_hash: str = ""
    record_count: int = 0
    metrics: dict[str, float] = Field(default_factory=dict)
    executed: bool = Field(default=False, description="False for --dry-run (no training run).")
    notes: str = ""
    environment: dict[str, str] = Field(
        default_factory=lambda: {
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
    )

    def to_markdown(self) -> str:
        """Render the manifest as a ``runs/``-style acceptance note."""
        lines = [
            f"# Run Manifest — {self.run_id}",
            "",
            f"- **method:** {self.method}",
            f"- **target:** {self.target}",
            f"- **seed:** {self.seed}",
            f"- **created:** {self.created_ts}",
            f"- **executed:** {self.executed}  (False = dry-run, no training)",
            f"- **data_hash:** `{self.data_hash}`",
            f"- **record_count:** {self.record_count}",
            "",
            "## Config",
            "```json",
            json.dumps(self.config, indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Metrics",
            "```json",
            json.dumps(self.metrics, indent=2, sort_keys=True, default=str),
            "```",
            "",
            "## Environment",
            "```json",
            json.dumps(self.environment, indent=2, sort_keys=True, default=str),
            "```",
        ]
        if self.notes:
            lines += ["", "## Notes", self.notes]
        return "\n".join(lines) + "\n"

    def write(self, out_dir: str | Path) -> Path:
        """Write ``manifest.json`` + ``manifest.md`` under ``out_dir`` and return the dir.

        Creates the directory if needed. This is the only filesystem side effect and is
        safe on CPU (writes a tiny note, runs no training).
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8"
        )
        (out / "manifest.md").write_text(self.to_markdown(), encoding="utf-8")
        return out
