"""
edge/planner/handoff.py — Onset / handoff policy (Phase 8C)
===========================================================
Owner: edge/runtime agent (final_use.md §4, Phase 8C).

Decides the boundary between an early onset (filler / speculative draft) and the real
speech-native output:

* when the filler ends,
* when the real output takes over, and
* how to suppress duplicated content so the user never hears a "double response".

The controller is a small explicit state machine (``idle → filler → handoff → main``)
that emits :class:`HandoffAction` decisions. It tracks what has already been spoken and
deduplicates the real output's leading content against the filler so the onset is smooth
and non-repetitive ("user hears smooth onset and no awkward double responses").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from edge.session.logging_hooks import get_logger

logger = get_logger(__name__)


class OnsetState(str, Enum):
    idle = "idle"
    filler_playing = "filler_playing"
    handing_off = "handing_off"
    main_playing = "main_playing"
    done = "done"


class HandoffKind(str, Enum):
    """The action the runtime should take for an onset/handoff step."""

    start_filler = "start_filler"
    suppress_filler_start = "suppress_filler_start"   # main is already ready; skip filler.
    crossfade = "crossfade"                           # blend filler tail into main onset.
    stop_filler = "stop_filler"                       # hard stop filler, then start main.
    play_main = "play_main"
    suppress_main = "suppress_main"                   # nothing left after dedup → no double.
    noop = "noop"


@dataclass
class HandoffAction:
    """A single onset/handoff decision returned to the runtime."""

    kind: HandoffKind
    text: str = ""                  # the (possibly de-duplicated) content to speak.
    crossfade_ms: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "crossfade_ms": self.crossfade_ms,
            "reason": self.reason,
        }


def _strip_word_punct(word: str) -> str:
    """Lowercase a token and strip surrounding punctuation for comparison."""
    return word.lower().strip(" ,.;:!?-—\"'()")


def _strip_leading_duplicate(filler_text: str, main_text: str) -> str:
    """Remove a leading copy of the filler from the main output to avoid repetition.

    Handles the common case where the main output begins by repeating the filler (e.g.
    filler "okay" + main "okay, here's what I found" → "here's what I found"). Matching
    is whitespace/case/punctuation-insensitive and word-aligned; punctuation is trimmed
    at the seam.
    """
    fwords = [w for w in (_strip_word_punct(w) for w in filler_text.split()) if w]
    if not fwords:
        return main_text.strip()
    mwords = main_text.split()
    mwords_cmp = [_strip_word_punct(w) for w in mwords]

    # Find how many leading words of main match the filler words.
    overlap = 0
    for i in range(min(len(fwords), len(mwords_cmp))):
        if mwords_cmp[i] == fwords[i]:
            overlap += 1
        else:
            break

    if overlap == 0:
        return main_text.strip()

    remainder = " ".join(mwords[overlap:]).strip()
    # Trim leading punctuation/separators left at the seam.
    return remainder.lstrip(" ,.;:-—")


@dataclass
class HandoffController:
    """Explicit onset/handoff state machine with duplicate suppression.

    Typical flow:
        ``begin_filler(text)`` → (main becomes ready) → ``handoff_to_main(main_text)``
        → ``complete()``.

    If the main output is ready *before* any filler was started, ``handoff_to_main``
    returns a ``play_main`` action and no filler is ever played.
    """

    crossfade_ms: int = 80
    _state: OnsetState = field(default=OnsetState.idle, init=False)
    _filler_text: str = field(default="", init=False)
    _spoken: list[str] = field(default_factory=list, init=False)

    @property
    def state(self) -> OnsetState:
        return self._state

    @property
    def spoken_text(self) -> str:
        """Everything committed to playback so far (for audit / dedup checks)."""
        return " ".join(part for part in self._spoken if part).strip()

    def begin_filler(self, filler_text: str) -> HandoffAction:
        """Start playing a filler onset. Rejected (noop) if we are past the filler stage."""
        if self._state not in (OnsetState.idle,):
            logger.debug("filler_start_ignored", state=self._state.value)
            return HandoffAction(HandoffKind.noop, reason=f"cannot start filler in {self._state.value}")
        self._state = OnsetState.filler_playing
        self._filler_text = filler_text
        self._spoken.append(filler_text)
        logger.info("filler_started", text=filler_text)
        return HandoffAction(HandoffKind.start_filler, text=filler_text, reason="filler onset")

    def handoff_to_main(self, main_text: str, *, filler_done: bool = True) -> HandoffAction:
        """Hand off to the real output, suppressing any duplicated leading content.

        Args:
            main_text: The real speech-native output text (or its leading window).
            filler_done: Whether the filler has finished playing. If not, we crossfade
                instead of hard-stopping, for a smoother seam.

        Returns:
            A :class:`HandoffAction`. If, after removing the duplicated filler prefix,
            there is nothing left to say, returns ``suppress_main`` so the user never
            hears a double response.
        """
        if self._state == OnsetState.main_playing:
            return HandoffAction(HandoffKind.noop, reason="main already playing")
        if self._state == OnsetState.done:
            return HandoffAction(HandoffKind.noop, reason="onset already completed")

        # Case A: no filler was ever played → just play the main output.
        if self._state == OnsetState.idle:
            self._state = OnsetState.main_playing
            self._spoken.append(main_text)
            logger.info("main_started_no_filler", chars=len(main_text))
            return HandoffAction(HandoffKind.play_main, text=main_text.strip(), reason="no filler; direct main")

        # Case B: filler is/was playing → dedup the main output against the filler.
        deduped = _strip_leading_duplicate(self._filler_text, main_text)
        self._state = OnsetState.handing_off

        if not deduped:
            # Main output is fully contained in the filler → suppress to avoid a double.
            self._state = OnsetState.main_playing
            logger.info("main_suppressed_duplicate", filler=self._filler_text)
            return HandoffAction(
                HandoffKind.suppress_main,
                text="",
                reason="main fully duplicated by filler; suppressed",
            )

        self._state = OnsetState.main_playing
        self._spoken.append(deduped)
        if filler_done:
            logger.info("handoff_stop_filler", chars=len(deduped))
            return HandoffAction(
                HandoffKind.stop_filler,
                text=deduped,
                reason="filler finished; main takes over (deduped)",
            )
        logger.info("handoff_crossfade", chars=len(deduped), crossfade_ms=self.crossfade_ms)
        return HandoffAction(
            HandoffKind.crossfade,
            text=deduped,
            crossfade_ms=self.crossfade_ms,
            reason="crossfade filler tail into main (deduped)",
        )

    def suppress_filler(self, reason: str = "main_ready_first") -> HandoffAction:
        """Skip the filler entirely because the main output is already available."""
        if self._state != OnsetState.idle:
            return HandoffAction(HandoffKind.noop, reason=f"cannot suppress filler in {self._state.value}")
        logger.info("filler_suppressed", reason=reason)
        return HandoffAction(HandoffKind.suppress_filler_start, reason=reason)

    def complete(self) -> HandoffAction:
        """Mark the onset/handoff as complete."""
        self._state = OnsetState.done
        return HandoffAction(HandoffKind.noop, reason="onset complete")

    def reset(self) -> None:
        """Reset for a new turn."""
        self._state = OnsetState.idle
        self._filler_text = ""
        self._spoken = []
