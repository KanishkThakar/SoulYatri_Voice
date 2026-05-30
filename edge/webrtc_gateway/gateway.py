"""
SoulYatri Edge — WebRTC + Opus Transport Gateway (Phase 2B, server side)
========================================================================
Transport-gateway contract that ingests :class:`shared.contracts.AudioFrame`
packets from the realtime client (WebRTC/Opus or the bring-up WebSocket path)
and **survives reconnects** while keeping frame ordering stable under moderate
network jitter.

Design goals (final_use.md §Phase-2B, §3.3 definition of done)
--------------------------------------------------------------
* **Reconnect survival** — a session is identified by ``session_id``. When a
  transport connection drops and the client reconnects with the same id, the
  accumulated session state (metadata, sequence cursor, jitter buffer) is
  preserved and resumed rather than discarded. State is only dropped after an
  explicit ``close_session`` or a TTL sweep.
* **Frame ingest** — frames are validated against the shared contract, ordered
  by ``seq`` through a small jitter buffer, de-duplicated, and handed to a sink.
* **Jitter smoothing** — a bounded reorder buffer releases frames in monotonic
  ``seq`` order, holding briefly for out-of-order arrivals.
* **CPU-only / lazy heavy deps** — ``aiortc`` / LiveKit are *optional*. They are
  imported lazily inside :func:`probe_webrtc_backend`; everything in this module
  works with an in-memory transport double so tests run with no native deps.
* **Visible logging** — every meaningful transition emits a structured log line.

The importable, dependency-light core is :class:`InMemoryTransportGateway`,
used directly by the pytest suite as the transport test double.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum

from shared.contracts import AudioFrame, now_ms

__all__ = [
    "ConnectionState",
    "SessionMetadata",
    "JitterBuffer",
    "GatewaySession",
    "TransportGateway",
    "InMemoryTransportGateway",
    "WebRTCBackendInfo",
    "probe_webrtc_backend",
]

logger = logging.getLogger("soulyatri.edge.webrtc_gateway")


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------
class ConnectionState(str, Enum):
    """Lifecycle of a single transport connection backing a session."""

    new = "new"
    connected = "connected"
    disconnected = "disconnected"  # transport dropped; session state retained
    closed = "closed"  # session explicitly torn down; state released


# ---------------------------------------------------------------------------
# Session metadata
# ---------------------------------------------------------------------------
@dataclass
class SessionMetadata:
    """Per-session bookkeeping that must survive reconnects."""

    session_id: str
    created_ms: int = field(default_factory=now_ms)
    last_active_ms: int = field(default_factory=now_ms)
    reconnect_count: int = 0
    frames_ingested: int = 0
    frames_dropped: int = 0  # duplicates / stale (already-delivered) frames
    sample_rate: int = 16000
    # Free-form metadata the client attaches on connect (codec, locale, ua...).
    attributes: dict = field(default_factory=dict)

    def touch(self) -> None:
        self.last_active_ms = now_ms()


# ---------------------------------------------------------------------------
# Jitter buffer
# ---------------------------------------------------------------------------
class JitterBuffer:
    """Bounded reorder buffer that releases frames in monotonic ``seq`` order.

    Frames may arrive out of order under network jitter. We hold a small window
    keyed by ``seq`` and release as soon as the next expected ``seq`` is present.
    If the buffer exceeds ``max_pending`` we release the lowest-``seq`` frame to
    bound memory and latency (graceful degradation rather than unbounded wait).

    De-duplication: a frame whose ``seq`` is below the next-expected cursor is a
    stale/duplicate and is reported via the returned ``dropped`` flag.
    """

    def __init__(self, max_pending: int = 32, start_seq: int = 0) -> None:
        self.max_pending = max_pending
        self._next_seq = start_seq
        self._pending: dict[int, AudioFrame] = {}

    @property
    def next_seq(self) -> int:
        return self._next_seq

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def reset_cursor(self, next_seq: int) -> None:
        """Resume ordering from ``next_seq`` (used on reconnect)."""
        self._next_seq = next_seq

    def push(self, frame: AudioFrame) -> tuple[list[AudioFrame], bool]:
        """Insert a frame; return ``(released_frames, was_dropped)``.

        ``released_frames`` are the frames now deliverable in order.
        ``was_dropped`` is True when the frame was a duplicate/stale arrival.
        """
        if frame.seq < self._next_seq:
            # Already delivered → duplicate / stale.
            return [], True
        if frame.seq in self._pending:
            # Duplicate still pending.
            return [], True

        self._pending[frame.seq] = frame

        # Overflow protection: never let the buffer grow without bound.
        if len(self._pending) > self.max_pending:
            lowest = min(self._pending)
            # Skip the gap: advance the cursor to the lowest buffered seq.
            if lowest > self._next_seq:
                self._next_seq = lowest

        return self._drain(), False

    def flush(self) -> list[AudioFrame]:
        """Release everything currently buffered in ``seq`` order (e.g. on final)."""
        released = [self._pending[s] for s in sorted(self._pending)]
        self._pending.clear()
        if released:
            self._next_seq = released[-1].seq + 1
        return released

    def _drain(self) -> list[AudioFrame]:
        released: list[AudioFrame] = []
        while self._next_seq in self._pending:
            frame = self._pending.pop(self._next_seq)
            released.append(frame)
            self._next_seq += 1
        return released


# ---------------------------------------------------------------------------
# Gateway session
# ---------------------------------------------------------------------------
# A sink receives frames once they are released in order by the jitter buffer.
FrameSink = Callable[[AudioFrame], None]


class GatewaySession:
    """In-order audio sink for one logical client session.

    Holds the jitter buffer, metadata, connection state, and the ordered frame
    log. Survives reconnects: dropping the connection moves the session to
    ``disconnected`` but keeps all state; a subsequent ``mark_connected`` resumes.
    """

    def __init__(
        self,
        session_id: str,
        *,
        sample_rate: int = 16000,
        max_pending: int = 32,
        retain_log: bool = True,
        sink: FrameSink | None = None,
    ) -> None:
        self.metadata = SessionMetadata(session_id=session_id, sample_rate=sample_rate)
        self.state = ConnectionState.new
        self._jitter = JitterBuffer(max_pending=max_pending)
        self._sink = sink
        self._retain_log = retain_log
        # Ordered record of every frame delivered to the sink (observability/replay).
        self.delivered: list[AudioFrame] = []

    @property
    def session_id(self) -> str:
        return self.metadata.session_id

    @property
    def is_active(self) -> bool:
        return self.state in (ConnectionState.new, ConnectionState.connected)

    # -- connection lifecycle -------------------------------------------------
    def mark_connected(self) -> None:
        """Transition to connected. If we were disconnected, this is a reconnect."""
        if self.state == ConnectionState.disconnected:
            self.metadata.reconnect_count += 1
            # Resume ordering from the cursor we had before the drop.
            logger.info(
                "session_reconnect session_id=%s reconnect_count=%d resume_seq=%d",
                self.session_id,
                self.metadata.reconnect_count,
                self._jitter.next_seq,
            )
        else:
            logger.info("session_connect session_id=%s", self.session_id)
        self.state = ConnectionState.connected
        self.metadata.touch()

    def mark_disconnected(self) -> None:
        """Transport dropped. Retain all state so the client can resume."""
        if self.state == ConnectionState.closed:
            return
        self.state = ConnectionState.disconnected
        self.metadata.touch()
        logger.warning(
            "session_disconnect session_id=%s frames_ingested=%d pending=%d",
            self.session_id,
            self.metadata.frames_ingested,
            self._jitter.pending_count,
        )

    def close(self) -> None:
        """Explicit teardown: flush remaining frames and release state."""
        leftover = self._jitter.flush()
        for frame in leftover:
            self._deliver(frame)
        self.state = ConnectionState.closed
        self.metadata.touch()
        logger.info(
            "session_close session_id=%s frames_ingested=%d frames_dropped=%d delivered=%d",
            self.session_id,
            self.metadata.frames_ingested,
            self.metadata.frames_dropped,
            len(self.delivered),
        )

    # -- frame ingest ---------------------------------------------------------
    def ingest(self, frame: AudioFrame) -> list[AudioFrame]:
        """Ingest one frame; return the frames released to the sink (in order)."""
        if self.state == ConnectionState.closed:
            raise RuntimeError(f"session {self.session_id} is closed")
        if frame.session_id != self.session_id:
            raise ValueError(
                f"frame.session_id={frame.session_id!r} != session {self.session_id!r}"
            )

        # An ingest implicitly (re)activates the connection.
        if self.state in (ConnectionState.new, ConnectionState.disconnected):
            self.mark_connected()

        released, dropped = self._jitter.push(frame)
        if dropped:
            self.metadata.frames_dropped += 1
            logger.debug(
                "frame_dropped session_id=%s seq=%d reason=stale_or_duplicate",
                self.session_id,
                frame.seq,
            )
            return []

        self.metadata.frames_ingested += 1
        self.metadata.touch()

        for f in released:
            self._deliver(f)

        if frame.is_final:
            # Release anything still buffered when the stream ends.
            for f in self._jitter.flush():
                self._deliver(f)
        return released

    def ingest_many(self, frames: Iterable[AudioFrame]) -> list[AudioFrame]:
        out: list[AudioFrame] = []
        for frame in frames:
            out.extend(self.ingest(frame))
        return out

    def _deliver(self, frame: AudioFrame) -> None:
        if self._retain_log:
            self.delivered.append(frame)
        if self._sink is not None:
            self._sink(frame)


# ---------------------------------------------------------------------------
# Transport gateway
# ---------------------------------------------------------------------------
class TransportGateway:
    """Manages sessions across transport connections; reconnect-survivable.

    This is the dependency-light core. A WebRTC/LiveKit backend wraps it by
    feeding decoded Opus → PCM into :meth:`ingest`; the gateway itself never
    needs native media libraries, which keeps the contract testable on CPU-only
    machines with no extra installs.
    """

    def __init__(self, *, max_pending: int = 32, session_ttl_ms: int = 60_000) -> None:
        self._sessions: dict[str, GatewaySession] = {}
        self._sinks: dict[str, FrameSink] = {}
        self.max_pending = max_pending
        self.session_ttl_ms = session_ttl_ms

    # -- session management ---------------------------------------------------
    def open_session(
        self,
        session_id: str,
        *,
        sample_rate: int = 16000,
        attributes: dict | None = None,
        sink: FrameSink | None = None,
    ) -> GatewaySession:
        """Open a new session, or **resume** an existing one (reconnect path)."""
        existing = self._sessions.get(session_id)
        if existing is not None and existing.state != ConnectionState.closed:
            # Reconnect: keep all accumulated state, just re-activate.
            if attributes:
                existing.metadata.attributes.update(attributes)
            if sink is not None:
                existing._sink = sink
                self._sinks[session_id] = sink
            existing.mark_connected()
            return existing

        resolved_sink = sink or self._sinks.get(session_id)
        session = GatewaySession(
            session_id,
            sample_rate=sample_rate,
            max_pending=self.max_pending,
            sink=resolved_sink,
        )
        if attributes:
            session.metadata.attributes.update(attributes)
        session.mark_connected()
        self._sessions[session_id] = session
        if resolved_sink is not None:
            self._sinks[session_id] = resolved_sink
        logger.info(
            "gateway_open_session session_id=%s sample_rate=%d total_sessions=%d",
            session_id,
            sample_rate,
            len(self._sessions),
        )
        return session

    def get_session(self, session_id: str) -> GatewaySession | None:
        return self._sessions.get(session_id)

    def disconnect(self, session_id: str) -> None:
        """Signal that the transport dropped without tearing the session down."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.mark_disconnected()

    def reconnect(
        self,
        session_id: str,
        *,
        sink: FrameSink | None = None,
    ) -> GatewaySession:
        """Resume a previously-opened session after a transport drop.

        If the session is unknown (e.g. expired), a fresh one is created so the
        client is never left without a sink.
        """
        session = self._sessions.get(session_id)
        if session is None or session.state == ConnectionState.closed:
            logger.warning(
                "reconnect_creates_new session_id=%s reason=unknown_or_closed", session_id
            )
            return self.open_session(session_id, sink=sink)
        if sink is not None:
            session._sink = sink
            self._sinks[session_id] = sink
        session.mark_connected()
        return session

    def ingest(self, frame: AudioFrame) -> list[AudioFrame]:
        """Route a frame to its session, opening one on demand."""
        session = self._sessions.get(frame.session_id)
        if session is None or session.state == ConnectionState.closed:
            session = self.open_session(frame.session_id, sample_rate=frame.sample_rate)
        return session.ingest(frame)

    def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.close()

    def sweep_expired(self, *, now: int | None = None) -> list[str]:
        """Release sessions idle longer than ``session_ttl_ms``. Returns removed ids."""
        cutoff = (now if now is not None else now_ms()) - self.session_ttl_ms
        removed: list[str] = []
        for sid, session in list(self._sessions.items()):
            if session.metadata.last_active_ms < cutoff:
                session.close()
                del self._sessions[sid]
                self._sinks.pop(sid, None)
                removed.append(sid)
        if removed:
            logger.info("gateway_sweep removed=%d ids=%s", len(removed), removed)
        return removed

    @property
    def active_session_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.is_active)


class InMemoryTransportGateway(TransportGateway):
    """Transport test double.

    Identical behavior to :class:`TransportGateway` but records every delivered
    frame per session in :attr:`received` so tests can assert ingest + reconnect
    survival without any real WebRTC/Opus transport.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.received: dict[str, list[AudioFrame]] = {}

    def open_session(self, session_id: str, **kwargs) -> GatewaySession:  # type: ignore[override]
        bucket = self.received.setdefault(session_id, [])
        user_sink = kwargs.pop("sink", None)

        def _sink(frame: AudioFrame) -> None:
            bucket.append(frame)
            if user_sink is not None:
                user_sink(frame)

        return super().open_session(session_id, sink=_sink, **kwargs)


# ---------------------------------------------------------------------------
# Optional WebRTC backend probe (lazy)
# ---------------------------------------------------------------------------
@dataclass
class WebRTCBackendInfo:
    """Result of probing for an optional realtime transport backend."""

    available: bool
    backend: str  # "aiortc", "livekit", or "none"
    detail: str = ""


def probe_webrtc_backend() -> WebRTCBackendInfo:
    """Detect an optional WebRTC/LiveKit backend **without** importing it eagerly.

    Heavy native transports are not required for the gateway contract or tests.
    This keeps the module importable on a CPU-only box with no media libraries
    installed; callers can branch on the result to wire a real backend when one
    is present.
    """
    import importlib.util

    for backend in ("aiortc", "livekit"):
        if importlib.util.find_spec(backend) is not None:
            logger.info("webrtc_backend_detected backend=%s", backend)
            return WebRTCBackendInfo(available=True, backend=backend)

    logger.info("webrtc_backend_fallback backend=none using=in_memory_transport")
    return WebRTCBackendInfo(
        available=False,
        backend="none",
        detail="aiortc/livekit not installed; use InMemoryTransportGateway for bring-up/tests",
    )
