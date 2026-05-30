"""
speech/moshi_runtime/service.py — Phase 6A: streaming speech-native runtime service.
====================================================================================

Design note (Phase 6A, final_use.md §Phase-6 / docs/INTERFACES.md §5.1)
-----------------------------------------------------------------------
Implements the :class:`SpeechRuntime` protocol:

    async def stream_reply(session_id, chunks: AsyncIterator[CodecChunk]) -> AsyncIterator[CodecChunk]
    async def cancel(session_id, turn_id) -> None

The runtime consumes **codec tokens + context state** (not text), streams output
incrementally (no full-sentence blocking), and exposes clean cancellation + repair hooks.

Backends (same pattern as the codec bridge):

* ``MoshiBackend`` — lazy-loads the real ``moshi`` package + weights inside a method,
  guarded by try/except. Never imported at module top level.
* ``EchoTransformBackend`` — deterministic CPU fallback. It does not "understand" speech;
  it transforms the user's codec tokens into a short, bounded, deterministic reply
  (token inversion + gentle attenuation across a fixed number of reply chunks) so the
  streaming contract — incremental output, cancellation, repair — is fully exercisable
  without weights. The reply is intentionally short and clearly synthetic.

Continuity (Phase 6B) lives in :mod:`session_runtime`; interruption/repair (Phase 6C) in
:mod:`repair`. This service wires them together around whichever backend is active.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from shared.contracts import CodecChunk, PersonaState, now_ms

from ..codec._compat import get_logger
from ..codec.mimi_bridge import CODEC_SAMPLE_RATE
from .repair import RepairController
from .session_runtime import SessionStore

log = get_logger(__name__)

__all__ = ["EchoTransformBackend", "MoshiBackend", "MoshiRuntimeService", "make_runtime"]

# Reply shaping for the fallback. Kept small so a "short turn streams to completion".
DEFAULT_MAX_REPLY_CHUNKS = 6
# Token grid midpoint (matches mimi_bridge mock 16-bit grid) used to invert tokens.
_TOKEN_MAX = 65535


class EchoTransformBackend:
    """Deterministic CPU fallback that turns user tokens into a short reply.

    Not a speech model — a reproducible transform so the streaming/cancel/repair contract
    is testable with no weights. For each accumulated user chunk it produces one reply
    chunk whose tokens are the *inverted, attenuated* user tokens, then emits a final empty
    chunk. Reply length is bounded by ``max_reply_chunks``.
    """

    name = "echo_transform"
    is_real = False

    def __init__(self, max_reply_chunks: int = DEFAULT_MAX_REPLY_CHUNKS) -> None:
        self.max_reply_chunks = max_reply_chunks

    def transform_tokens(self, tokens: list[int], *, step: int) -> list[int]:
        """Invert tokens around the grid midpoint and attenuate toward silence by step.

        Attenuation makes the synthetic reply fade over successive chunks (a clearly
        non-real, deterministic "winding down" reply), while inversion keeps it a function
        of the actual user input rather than a constant.
        """
        # gain shrinks each chunk: 1.0, 0.8, 0.64, ... so the reply tapers.
        gain = 0.8 ** step
        out: list[int] = []
        mid = _TOKEN_MAX / 2.0
        for t in tokens:
            inverted = _TOKEN_MAX - t
            attenuated = mid + (inverted - mid) * gain
            out.append(int(round(max(0, min(_TOKEN_MAX, attenuated)))))
        return out


class MoshiBackend:
    """Lazy adapter around the real Moshi speech-native runtime.

    The heavy import + weight load happens in :meth:`load`, guarded by try/except. If
    ``moshi``/weights are unavailable (this CPU/no-weights env), :meth:`load` raises and
    the service falls back to :class:`EchoTransformBackend`.
    """

    name = "moshi"
    is_real = True

    def __init__(self, weights_path: str | None = None, device: str = "cpu") -> None:
        self.weights_path = weights_path
        self.device = device
        self._model = None

    def load(self) -> None:
        try:
            import torch  # noqa: F401
            from moshi.models import loaders  # type: ignore

            if not self.weights_path:
                raise RuntimeError("no Moshi weights path configured (set MOSHI_WEIGHTS)")
            self._model = loaders.get_moshi_lm(self.weights_path, device=self.device)
            self._model.eval()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Moshi unavailable, falling back to echo runtime: {exc}") from exc


class MoshiRuntimeService:
    """``SpeechRuntime`` implementation (Phase 6A) with continuity + repair.

    Parameters
    ----------
    backend:
        ``"auto"`` (default), ``"moshi"`` (force real, raises if unavailable), or
        ``"echo"`` (force the CPU fallback).
    max_reply_chunks:
        Upper bound on fallback reply length (keeps short turns bounded).
    """

    def __init__(
        self,
        *,
        backend: str = "auto",
        weights_path: str | None = None,
        device: str = "cpu",
        max_reply_chunks: int = DEFAULT_MAX_REPLY_CHUNKS,
        sessions: SessionStore | None = None,
        repair: RepairController | None = None,
    ) -> None:
        self._weights_path = weights_path or os.environ.get("MOSHI_WEIGHTS")
        self._device = device
        self.max_reply_chunks = max_reply_chunks
        self.sessions = sessions or SessionStore()
        self.repair = repair or RepairController()
        self._backend = self._select_backend(backend)
        log.info(
            "runtime_init",
            backend=self.backend_name,
            is_real=self._backend.is_real,
            max_reply_chunks=self.max_reply_chunks,
        )

    # -- backend selection -------------------------------------------------
    def _select_backend(self, backend: str):  # noqa: ANN202
        if backend == "echo":
            return EchoTransformBackend(self.max_reply_chunks)
        if backend in ("auto", "moshi"):
            moshi = MoshiBackend(self._weights_path, self._device)
            try:
                moshi.load()
                log.info("runtime_backend_selected", backend="moshi")
                return moshi
            except Exception as exc:  # noqa: BLE001
                if backend == "moshi":
                    raise
                log.warning(
                    "runtime_backend_fallback",
                    requested="moshi",
                    using="echo_transform",
                    reason=str(exc),
                    note="NOT final architecture; deterministic echo runtime (CPU/no-weights).",
                )
                return EchoTransformBackend(self.max_reply_chunks)
        raise ValueError(f"unknown backend: {backend!r}")

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def is_real_backend(self) -> bool:
        return self._backend.is_real

    # -- SpeechRuntime API -------------------------------------------------
    async def stream_reply(
        self, session_id: str, chunks: AsyncIterator[CodecChunk]
    ) -> AsyncIterator[CodecChunk]:
        """Consume a user codec-token stream and yield a reply codec-token stream.

        Streaming + cancellable. The turn id is taken from the first inbound chunk (or
        synthesized). Output is emitted incrementally; the loop checks the repair control's
        cancel flag between chunks so a barge-in stops generation without deadlock.
        """
        state = self.sessions.get_or_create(session_id)

        # 1) Ingest the user turn (bounded) while honoring continuity counters.
        user_tokens: list[int] = []
        turn_id: str | None = None
        async for chunk in chunks:
            if turn_id is None:
                turn_id = chunk.turn_id or f"{session_id}-t{state.turn_counter + 1}"
                state.begin_turn(turn_id)
                self.repair.register(session_id, turn_id)
            self.sessions.observe_input(session_id, chunk)
            user_tokens.extend(chunk.codec_tokens)
            if chunk.is_final:
                break

        if turn_id is None:
            # Empty input stream: nothing to reply to. Emit a single final empty chunk.
            turn_id = f"{session_id}-t{state.turn_counter + 1}"
            state.begin_turn(turn_id)
            self.repair.register(session_id, turn_id)

        control = self.repair.get(session_id, turn_id)
        assert control is not None
        log.info("turn_started", session_id=session_id, turn_id=turn_id, in_tokens=len(user_tokens))

        # 2) Generate a bounded reply, chunk by chunk, checking cancellation.
        sample_rate = CODEC_SAMPLE_RATE
        n_reply = self._reply_chunk_count(user_tokens)
        emitted = 0
        try:
            for step in range(n_reply):
                if control.cancelled:
                    log.info("turn_generation_stopped", session_id=session_id, turn_id=turn_id,
                             emitted=emitted, reason="cancelled")
                    break
                # Yield control so a concurrent cancel() is observed promptly.
                await asyncio.sleep(0)
                if control.cancelled:
                    break
                reply_tokens = self._reply_tokens(user_tokens, step=step)
                is_final = step == n_reply - 1
                out = CodecChunk(
                    turn_id=turn_id,
                    seq=step,
                    codec_tokens=reply_tokens,
                    ts_ms=now_ms(),
                    is_final=is_final,
                    sample_rate=sample_rate,
                )
                control.note_emit(step)
                self.sessions.observe_output(session_id, out)
                emitted += 1
                yield out
        finally:
            cancelled = control.cancelled
            state.end_turn(turn_id, cancelled=cancelled)
            if cancelled:
                self.repair.rollback(session_id, turn_id)
            log.info("turn_finished", session_id=session_id, turn_id=turn_id,
                     emitted=emitted, cancelled=cancelled)

    async def cancel(self, session_id: str, turn_id: str) -> None:
        """Interruption hook: cooperatively cancel an in-flight turn (clean stop)."""
        self.repair.cancel(session_id, turn_id)

    # -- reply shaping -----------------------------------------------------
    def _reply_chunk_count(self, user_tokens: list[int]) -> int:
        if self.is_real_backend:  # pragma: no cover - needs weights
            return self.max_reply_chunks
        # Fallback: scale reply length with input but stay bounded + at least 1.
        approx = max(1, min(self.max_reply_chunks, 1 + len(user_tokens) // 4096))
        return approx

    def _reply_tokens(self, user_tokens: list[int], *, step: int) -> list[int]:
        if self.is_real_backend:  # pragma: no cover - needs weights
            raise RuntimeError("real backend generation not available without weights")
        # Use a bounded slice of the user tokens as the basis for this reply chunk.
        if not user_tokens:
            base = [_TOKEN_MAX // 2] * 240  # short neutral hum
        else:
            window = 480
            start = (step * window) % max(1, len(user_tokens))
            base = user_tokens[start : start + window] or user_tokens[:window]
        return self._backend.transform_tokens(base, step=step)

    # -- continuity helpers ------------------------------------------------
    def set_persona(self, session_id: str, persona: PersonaState) -> None:
        self.sessions.get_or_create(session_id, persona)

    def session_context(self, session_id: str) -> dict:
        state = self.sessions.get(session_id)
        return state.context_digest() if state else {"session_id": session_id, "n_turns": 0}

    def stats(self) -> dict:
        return {
            "backend": self.backend_name,
            "is_real": self.is_real_backend,
            "sessions": self.sessions.stats(),
            "repair": self.repair.stats(),
        }


def make_runtime(**kwargs) -> MoshiRuntimeService:
    """Factory returning a :class:`MoshiRuntimeService` (auto backend by default)."""
    return MoshiRuntimeService(**kwargs)
