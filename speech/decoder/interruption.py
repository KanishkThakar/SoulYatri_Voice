"""
speech/decoder/interruption.py — Phase 10C: playback interruption control.
==========================================================================

Design note (Phase 10C, final_use.md §Phase-10)
-----------------------------------------------
When the user barges in, the assistant's audio must stop *within a budget* and *cleanly*
(no click, no half-played buffer left ringing). This module owns that decision:

* **policy** — ``FADE`` (apply a short linear fade-out so the stop is inaudible) or
  ``HARD_CUT`` (drop remaining audio immediately; lowest latency, may click). Default is
  ``FADE`` because it sounds natural; commands/urgent stops can request ``HARD_CUT``.
* **budget** — a stop must complete within ``stop_budget_ms``. The fade length is clamped
  so the fade itself never exceeds the budget.
* **state sync** — :meth:`interrupt` returns an :class:`InterruptionResult` describing
  exactly what was played vs discarded and a ``client_action`` ("fade"/"flush") so the
  server and client converge on the same playback state.

The controller is transport-agnostic: it operates on PCM buffers (the decoder hands it the
audio it was about to play) and tells the caller what to actually emit. It pairs with the
runtime's :class:`speech.moshi_runtime.repair.RepairController` — that one stops *token
generation*; this one stops *waveform playback*.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from ..codec._compat import get_logger
from ..codec._dsp import linear_fade

log = get_logger(__name__)

__all__ = ["StopPolicy", "InterruptionResult", "PlaybackInterruptionController"]

# Default budget within which playback must stop after a barge-in.
DEFAULT_STOP_BUDGET_MS = 50
# Default fade length when policy == FADE.
DEFAULT_FADE_MS = 20


class StopPolicy(str, Enum):
    """How to stop audio on interruption."""

    fade = "fade"
    hard_cut = "hard_cut"


@dataclass
class InterruptionResult:
    """Outcome of an interruption, used to sync server + client playback state."""

    interrupted: bool
    policy: StopPolicy
    played_samples: int
    discarded_samples: int
    fade_samples: int
    stop_latency_ms: float
    client_action: str  # "fade" | "flush" | "none"
    within_budget: bool
    final_pcm: list[float] = field(default_factory=list)


class PlaybackInterruptionController:
    """Stops decoded playback cleanly on barge-in, by policy, within a budget.

    Parameters
    ----------
    sample_rate:
        Playback sample rate (for ms<->samples conversion).
    policy:
        Default :class:`StopPolicy`.
    stop_budget_ms:
        Max time the stop may take. Fade length is clamped to this.
    fade_ms:
        Fade-out length when policy == FADE.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 24000,
        policy: StopPolicy = StopPolicy.fade,
        stop_budget_ms: int = DEFAULT_STOP_BUDGET_MS,
        fade_ms: int = DEFAULT_FADE_MS,
    ) -> None:
        self.sample_rate = sample_rate
        self.policy = policy
        self.stop_budget_ms = stop_budget_ms
        self.fade_ms = fade_ms
        self._interrupted = False

    @property
    def interrupted(self) -> bool:
        return self._interrupted

    def reset(self) -> None:
        """Clear interruption state for a new turn."""
        self._interrupted = False

    def _ms_to_samples(self, ms: int) -> int:
        return max(0, int(self.sample_rate * ms / 1000))

    def interrupt(
        self,
        pending_pcm: list[float],
        *,
        policy: StopPolicy | None = None,
    ) -> InterruptionResult:
        """Stop playback of ``pending_pcm`` (the buffer about to be played).

        Returns an :class:`InterruptionResult`. With ``FADE`` the result's ``final_pcm`` is
        the faded leading portion (played out gently); with ``HARD_CUT`` it is empty
        (everything pending is discarded immediately).
        """
        start = time.perf_counter()
        chosen = policy or self.policy
        self._interrupted = True
        budget_samples = self._ms_to_samples(self.stop_budget_ms)

        if chosen is StopPolicy.hard_cut:
            result = InterruptionResult(
                interrupted=True,
                policy=chosen,
                played_samples=0,
                discarded_samples=len(pending_pcm),
                fade_samples=0,
                stop_latency_ms=(time.perf_counter() - start) * 1000.0,
                client_action="flush",
                within_budget=True,  # hard cut is immediate by definition
                final_pcm=[],
            )
            log.info("playback_interrupted", policy="hard_cut",
                     discarded=result.discarded_samples)
            return result

        # FADE: play a short faded head, discard the rest. Fade clamped to budget.
        fade_samples = min(self._ms_to_samples(self.fade_ms), budget_samples, len(pending_pcm))
        head = pending_pcm[:fade_samples]
        faded = linear_fade(head, fade_samples, fade_out=True)
        latency_ms = (time.perf_counter() - start) * 1000.0
        # The audible stop duration is the fade length in ms (bounded by budget_samples).
        fade_duration_ms = fade_samples / self.sample_rate * 1000.0 if self.sample_rate else 0.0
        within_budget = fade_duration_ms <= self.stop_budget_ms + 1e-6
        result = InterruptionResult(
            interrupted=True,
            policy=chosen,
            played_samples=len(faded),
            discarded_samples=len(pending_pcm) - len(faded),
            fade_samples=fade_samples,
            stop_latency_ms=latency_ms,
            client_action="fade",
            within_budget=within_budget,
            final_pcm=faded,
        )
        log.info(
            "playback_interrupted",
            policy="fade",
            played=result.played_samples,
            discarded=result.discarded_samples,
            fade_ms=round(fade_duration_ms, 3),
            within_budget=within_budget,
        )
        return result
