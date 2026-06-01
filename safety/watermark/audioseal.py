"""
safety/watermark/audioseal.py — Synthesized-audio watermarking (Phase 11C).
=============================================================================
Owner: safety agent (final_use.md §4, Phase 11C; DECISIONS.md D-007/D-008).

Every synthesized-audio output path — including fallbacks — MUST be watermarked before
emission, and an output whose watermark cannot be verified is **flagged non-compliant and
NOT emitted**.

This module provides:
  * An :class:`AudioSeal`-style interface (``embed`` / ``detect``) that lazily loads the
    real AudioSeal model when available, and a **deterministic fallback marker** otherwise
    so watermarking always works on a CPU-only box with no weights (D-008).
  * :class:`Watermarker` — the high-level API used by the speech/decoder and aux/fallback
    teams: ``protect()`` watermarks + self-verifies in one call and only returns a
    ``compliant`` result if verification passes.
  * Detector-outcome logging to an auditable :class:`AuditLog`.
  * Ops tooling (``ops_status`` / ``main``) to inspect backend + run a self-check.

Fail CLOSED: if embedding or verification raises or the detector is uncertain, the audio
is marked non-compliant.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from typing import Protocol

from safety.contracts import (
    AuditLog,
    WatermarkedAudio,
    WatermarkMarker,
    WatermarkResult,
    get_logger,
    sign,
    verify_signature,
)

__all__ = [
    "DEFAULT_PAYLOAD",
    "WatermarkBackend",
    "DeterministicFallbackBackend",
    "Watermarker",
    "WatermarkComplianceError",
    "ops_status",
    "main",
]

_log = get_logger("safety.watermark")

DEFAULT_PAYLOAD = "SOULYATRI"
_FALLBACK_BACKEND = "deterministic_fallback"
_AUDIOSEAL_BACKEND = "audioseal"


class WatermarkBackend(Protocol):
    """Interface every watermark backend implements (AudioSeal-compatible shape)."""

    name: str

    def embed(
        self, samples: Sequence[float], sample_rate: int, payload: str
    ) -> WatermarkedAudio: ...

    def detect(
        self, samples: Sequence[float], sample_rate: int, marker: WatermarkMarker
    ) -> WatermarkResult: ...


# Optional hook to inject a real AudioSeal-backed backend (lazy; never imported at top).
load_audioseal_backend: Callable[[], WatermarkBackend] | None = None


def _audio_digest(samples: Sequence[float], sample_rate: int) -> str:
    """Stable digest of audio content for the fallback signature.

    Quantizes floats to int16-ish bins so tiny floating noise doesn't change the digest,
    while any real tampering (inserted/removed/edited samples) does.
    """
    h = hashlib.sha256()
    h.update(str(sample_rate).encode("utf-8"))
    h.update(str(len(samples)).encode("utf-8"))
    for s in samples:
        # clamp + quantize to 1/10000 resolution
        q = int(max(-1.0, min(1.0, float(s))) * 10000)
        h.update(q.to_bytes(4, "big", signed=True))
    return h.hexdigest()


class DeterministicFallbackBackend:
    """CPU-only watermark backend: embeds an inaudible marker + HMAC signature.

    The "embed" step applies a tiny deterministic perturbation (a fixed low-amplitude
    pattern) so the output is provably transformed, then records an HMAC signature over
    the payload + post-embed audio digest. ``detect`` recomputes and verifies it.
    """

    name = _FALLBACK_BACKEND
    _EPS = 1e-4  # marker amplitude: negligible but deterministic

    def embed(self, samples: Sequence[float], sample_rate: int, payload: str) -> WatermarkedAudio:
        marked: list[float] = []
        for i, s in enumerate(samples):
            # deterministic, payload-independent micro-dither; clamped to [-1, 1]
            delta = self._EPS * math.sin(i * 0.5)
            marked.append(max(-1.0, min(1.0, float(s) + delta)))
        digest = _audio_digest(marked, sample_rate)
        signature = sign(payload, digest)
        marker = WatermarkMarker(
            payload=payload,
            signature=signature,
            backend=self.name,
            sample_rate=sample_rate,
            num_samples=len(marked),
        )
        # compliant flag is set by the Watermarker after self-verify, not here.
        return WatermarkedAudio(
            samples=marked, sample_rate=sample_rate, marker=marker, compliant=False
        )

    def detect(
        self, samples: Sequence[float], sample_rate: int, marker: WatermarkMarker
    ) -> WatermarkResult:
        digest = _audio_digest(samples, sample_rate)
        ok = verify_signature(marker.signature, marker.payload, digest)
        return WatermarkResult(
            detected=ok,
            score=1.0 if ok else 0.0,
            payload=marker.payload if ok else None,
            backend=self.name,
            compliant=ok,
            reason="signature_verified" if ok else "signature_mismatch",
        )


class Watermarker:
    """High-level watermark API for all synthesized-audio output paths.

    The speech decoder (Phase 10) and the classic fallback TTS path (Phase 13) must route
    EVERY output through :meth:`protect` before emission and only emit when
    ``result.compliant`` is True.
    """

    def __init__(
        self,
        *,
        backend: WatermarkBackend | None = None,
        audit_log: AuditLog | None = None,
        detect_threshold: float = 0.5,
        payload: str = DEFAULT_PAYLOAD,
    ) -> None:
        self._backend = backend
        self._backend_loaded = backend is not None
        self.audit = audit_log or AuditLog("watermark")
        self.detect_threshold = detect_threshold
        self.payload = payload

    # -- backend lazy-load ----------------------------------------------------
    def _get_backend(self) -> WatermarkBackend:
        if not self._backend_loaded:
            if load_audioseal_backend is not None:
                try:
                    self._backend = load_audioseal_backend()
                    _log.info("loaded AudioSeal backend")
                except Exception as exc:  # pragma: no cover - defensive, fall back
                    _log.warning("AudioSeal load failed, using deterministic fallback: %s", exc)
                    self._backend = DeterministicFallbackBackend()
            else:
                self._backend = DeterministicFallbackBackend()
            self._backend_loaded = True
        assert self._backend is not None
        return self._backend

    @property
    def backend_name(self) -> str:
        return self._get_backend().name

    # -- core operations ------------------------------------------------------
    def embed(self, samples: Sequence[float], sample_rate: int) -> WatermarkedAudio:
        """Insert a watermark; raises are converted to a non-compliant result upstream."""
        return self._get_backend().embed(list(samples), sample_rate, self.payload)

    def verify(
        self, samples: Sequence[float], sample_rate: int, marker: WatermarkMarker
    ) -> WatermarkResult:
        """Run the detector and log the outcome (auditable)."""
        try:
            result = self._get_backend().detect(list(samples), sample_rate, marker)
        except Exception as exc:  # fail closed
            audit = self.audit.record(
                "verify", "non_compliant", backend=self.backend_name, error=repr(exc)
            )
            return WatermarkResult(
                detected=False,
                score=0.0,
                backend=self.backend_name,
                compliant=False,
                reason="detector_error_fail_closed",
                audit_id=audit.audit_id,
            )
        compliant = result.detected and result.score >= self.detect_threshold
        result.compliant = compliant
        audit = self.audit.record(
            "verify",
            "compliant" if compliant else "non_compliant",
            backend=result.backend,
            detected=result.detected,
            score=result.score,
            payload=result.payload,
        )
        result.audit_id = audit.audit_id
        return result

    def protect(
        self, samples: Sequence[float], sample_rate: int
    ) -> tuple[WatermarkedAudio, WatermarkResult]:
        """Watermark + self-verify in one step. The ONLY entry point output paths need.

        Returns ``(watermarked, result)``. Callers MUST check ``result.compliant`` and
        refuse to emit audio when it is False (an unverifiable output is flagged
        non-compliant rather than emitted).
        """
        try:
            watermarked = self.embed(samples, sample_rate)
        except Exception as exc:  # fail closed — never emit unmarked audio
            audit = self.audit.record(
                "protect", "non_compliant", backend=self.backend_name, error=repr(exc)
            )
            # Build a placeholder marker so the contract is well-formed but non-compliant.
            marker = WatermarkMarker(
                payload=self.payload,
                signature="",
                backend=self.backend_name,
                sample_rate=sample_rate,
                num_samples=len(list(samples)),
            )
            bad = WatermarkedAudio(
                samples=[], sample_rate=sample_rate, marker=marker, compliant=False
            )
            result = WatermarkResult(
                detected=False,
                score=0.0,
                backend=self.backend_name,
                compliant=False,
                reason="embed_error_fail_closed",
                audit_id=audit.audit_id,
            )
            return bad, result

        result = self.verify(watermarked.samples, watermarked.sample_rate, watermarked.marker)
        watermarked.compliant = result.compliant
        self.audit.record(
            "protect",
            "compliant" if result.compliant else "non_compliant",
            backend=watermarked.marker.backend,
            num_samples=watermarked.marker.num_samples,
        )
        return watermarked, result

    def assert_compliant(self, result: WatermarkResult) -> None:
        """Raise if an output is not watermark-compliant (hard gate for emit paths)."""
        if not result.compliant:
            raise WatermarkComplianceError(
                f"audio failed watermark verification: {result.reason} (backend={result.backend})"
            )


class WatermarkComplianceError(RuntimeError):
    """Raised when an output cannot be verified and therefore must not be emitted."""


# ---------------------------------------------------------------------------
# Ops tooling
# ---------------------------------------------------------------------------
def ops_status(watermarker: Watermarker | None = None) -> dict:
    """Return backend + a self-check result for ops dashboards / CLI."""
    wm = watermarker or Watermarker()
    sample = [0.0, 0.25, -0.25, 0.5, -0.5, 0.1, -0.1, 0.0]
    _watermarked, result = wm.protect(sample, 24000)
    return {
        "backend": wm.backend_name,
        "detect_threshold": wm.detect_threshold,
        "payload": wm.payload,
        "self_check_compliant": result.compliant,
        "self_check_score": result.score,
        "audit_events": len(wm.audit),
    }


def main(argv: list[str] | None = None) -> int:
    """Tiny CLI: ``python -m safety.watermark.audioseal`` prints ops status as JSON."""
    import json

    status = ops_status()
    print(json.dumps(status, indent=2))
    return 0 if status["self_check_compliant"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
