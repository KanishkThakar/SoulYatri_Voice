"""
Tests for edge/webrtc_gateway/gateway.py.

Covers the two acceptance behaviors from final_use.md §Phase-2B:
  * frame ingest (validation, ordering, de-duplication, in-order delivery)
  * reconnect survival (state is retained across transport drops and resumed)

All tests run with the in-memory transport double — no aiortc/LiveKit required.
"""

from __future__ import annotations

import importlib

import pytest

from edge.webrtc_gateway.gateway import (
    ConnectionState,
    InMemoryTransportGateway,
    JitterBuffer,
    TransportGateway,
    probe_webrtc_backend,
)
from shared.contracts import AudioFrame


# ---------------------------------------------------------------------------
# Import hygiene / CPU-only safety
# ---------------------------------------------------------------------------
def test_module_imports_clean() -> None:
    mod = importlib.import_module("edge.webrtc_gateway.gateway")
    assert hasattr(mod, "TransportGateway")


def test_no_heavy_imports_loaded() -> None:
    import sys

    importlib.import_module("edge.webrtc_gateway.gateway")
    for heavy in ("torch", "aiortc", "livekit", "transformers"):
        assert heavy not in sys.modules, f"{heavy} must not be imported by the gateway"


def test_probe_backend_returns_info() -> None:
    info = probe_webrtc_backend()
    # On a bare CPU box this is "none"; if aiortc/livekit are present it reports them.
    assert info.backend in ("none", "aiortc", "livekit")
    assert isinstance(info.available, bool)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _frame(session_id: str, seq: int, *, final: bool = False, sr: int = 16000) -> AudioFrame:
    return AudioFrame(
        session_id=session_id,
        seq=seq,
        pcm=[0.0, float(seq) / 100.0],
        sample_rate=sr,
        is_final=final,
    )


def _seqs(frames) -> list[int]:
    return [f.seq for f in frames]


# ---------------------------------------------------------------------------
# JitterBuffer unit behavior
# ---------------------------------------------------------------------------
def test_jitter_buffer_in_order() -> None:
    jb = JitterBuffer()
    rel0, dropped0 = jb.push(_frame("s", 0))
    rel1, dropped1 = jb.push(_frame("s", 1))
    assert _seqs(rel0) == [0]
    assert _seqs(rel1) == [1]
    assert not dropped0 and not dropped1


def test_jitter_buffer_reorders_out_of_order() -> None:
    jb = JitterBuffer()
    rel2, _ = jb.push(_frame("s", 2))  # arrives first, held
    rel0, _ = jb.push(_frame("s", 0))
    rel1, _ = jb.push(_frame("s", 1))  # now 0,1,2 can flow
    assert _seqs(rel2) == []
    assert _seqs(rel0) == [0]
    assert _seqs(rel1) == [1, 2]


def test_jitter_buffer_dedupes_and_drops_stale() -> None:
    jb = JitterBuffer()
    jb.push(_frame("s", 0))
    jb.push(_frame("s", 1))
    # Re-send seq 0 (already delivered) → stale duplicate.
    rel, dropped = jb.push(_frame("s", 0))
    assert rel == []
    assert dropped is True


def test_jitter_buffer_overflow_skips_gap() -> None:
    jb = JitterBuffer(max_pending=4)
    # seq 0 never arrives; fill the buffer beyond capacity with future frames.
    for s in range(1, 7):
        jb.push(_frame("s", s))
    # Cursor must have advanced past the missing 0 to bound memory.
    assert jb.next_seq >= 1
    assert jb.pending_count <= 4 + 1


# ---------------------------------------------------------------------------
# Frame ingest
# ---------------------------------------------------------------------------
def test_ingest_delivers_in_order() -> None:
    gw = InMemoryTransportGateway()
    gw.open_session("s1", sample_rate=16000)
    for s in (0, 1, 2, 3):
        gw.ingest(_frame("s1", s))
    assert _seqs(gw.received["s1"]) == [0, 1, 2, 3]


def test_ingest_reorders_jittered_arrivals() -> None:
    gw = InMemoryTransportGateway()
    gw.open_session("s1")
    for s in (0, 2, 1, 3):
        gw.ingest(_frame("s1", s))
    assert _seqs(gw.received["s1"]) == [0, 1, 2, 3]


def test_ingest_auto_opens_session() -> None:
    gw = InMemoryTransportGateway()
    gw.ingest(_frame("auto", 0))
    assert gw.get_session("auto") is not None
    assert _seqs(gw.received["auto"]) == [0]


def test_ingest_rejects_mismatched_session_id() -> None:
    gw = TransportGateway()
    session = gw.open_session("s1")
    with pytest.raises(ValueError):
        session.ingest(_frame("other", 0))


def test_ingest_counts_drops() -> None:
    gw = InMemoryTransportGateway()
    gw.open_session("s1")
    gw.ingest(_frame("s1", 0))
    gw.ingest(_frame("s1", 1))
    gw.ingest(_frame("s1", 0))  # duplicate
    session = gw.get_session("s1")
    assert session is not None
    assert session.metadata.frames_dropped == 1
    assert session.metadata.frames_ingested == 2


def test_final_frame_flushes_buffer() -> None:
    gw = InMemoryTransportGateway()
    gw.open_session("s1")
    gw.ingest(_frame("s1", 0))
    # seq 2 held (gap at 1), then final at seq 1 should flush 1 and 2.
    gw.ingest(_frame("s1", 2))
    gw.ingest(_frame("s1", 1, final=True))
    assert _seqs(gw.received["s1"]) == [0, 1, 2]


# ---------------------------------------------------------------------------
# Reconnect survival
# ---------------------------------------------------------------------------
def test_reconnect_preserves_state_and_resumes_ordering() -> None:
    gw = InMemoryTransportGateway()
    gw.open_session("s1")
    gw.ingest(_frame("s1", 0))
    gw.ingest(_frame("s1", 1))

    # Transport drops.
    gw.disconnect("s1")
    session = gw.get_session("s1")
    assert session is not None
    assert session.state == ConnectionState.disconnected
    # State retained across the drop.
    assert session.metadata.frames_ingested == 2

    # Client reconnects with the same id and continues from seq 2.
    resumed = gw.reconnect("s1")
    assert resumed is session
    assert resumed.state == ConnectionState.connected
    assert resumed.metadata.reconnect_count == 1

    gw.ingest(_frame("s1", 2))
    gw.ingest(_frame("s1", 3))
    assert _seqs(gw.received["s1"]) == [0, 1, 2, 3]
    assert session.metadata.frames_ingested == 4


def test_reconnect_via_open_session_resumes_same_session() -> None:
    gw = InMemoryTransportGateway()
    first = gw.open_session("s1")
    gw.ingest(_frame("s1", 0))
    gw.disconnect("s1")
    # A client calling open_session again with the same id must resume, not reset.
    second = gw.open_session("s1")
    assert second is first
    assert second.metadata.reconnect_count == 1


def test_reconnect_unknown_session_creates_new() -> None:
    gw = InMemoryTransportGateway()
    session = gw.reconnect("never-seen")
    assert session is not None
    assert session.state == ConnectionState.connected


def test_ingest_after_drop_reactivates() -> None:
    gw = InMemoryTransportGateway()
    gw.open_session("s1")
    gw.ingest(_frame("s1", 0))
    gw.disconnect("s1")
    # Frames arriving after a silent drop implicitly reactivate the session.
    gw.ingest(_frame("s1", 1))
    session = gw.get_session("s1")
    assert session is not None
    assert session.state == ConnectionState.connected
    assert session.metadata.reconnect_count == 1
    assert _seqs(gw.received["s1"]) == [0, 1]


def test_dropped_frames_during_disconnect_resume_cleanly() -> None:
    """Frames lost mid-drop don't corrupt ordering after reconnect."""
    gw = InMemoryTransportGateway()
    gw.open_session("s1")
    gw.ingest(_frame("s1", 0))
    gw.ingest(_frame("s1", 1))
    gw.disconnect("s1")
    # seq 2,3 lost on the wire. Client reconnects and resends starting at 2.
    gw.reconnect("s1")
    for s in (2, 3, 4):
        gw.ingest(_frame("s1", s))
    assert _seqs(gw.received["s1"]) == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
def test_close_session_releases_and_flushes() -> None:
    gw = InMemoryTransportGateway()
    gw.open_session("s1")
    gw.ingest(_frame("s1", 0))
    gw.ingest(_frame("s1", 2))  # held (gap at 1)
    gw.close_session("s1")
    session = gw.get_session("s1")
    assert session is not None
    assert session.state == ConnectionState.closed
    # Close flushes the held frame.
    assert 2 in _seqs(gw.received["s1"])


def test_ingest_on_closed_session_raises() -> None:
    gw = InMemoryTransportGateway()
    session = gw.open_session("s1")
    session.close()
    with pytest.raises(RuntimeError):
        session.ingest(_frame("s1", 0))


def test_sweep_expired_releases_idle_sessions() -> None:
    gw = TransportGateway(session_ttl_ms=1000)
    session = gw.open_session("s1")
    # Force last activity far into the past.
    session.metadata.last_active_ms = 0
    removed = gw.sweep_expired(now=10_000)
    assert "s1" in removed
    assert gw.get_session("s1") is None


def test_active_session_count() -> None:
    gw = TransportGateway()
    gw.open_session("a")
    gw.open_session("b")
    gw.disconnect("b")  # disconnected sessions are retained but not "active"
    assert gw.active_session_count == 1


def test_session_attributes_carried_and_updated() -> None:
    gw = TransportGateway()
    gw.open_session("s1", attributes={"codec": "opus", "locale": "hi-IN"})
    gw.disconnect("s1")
    gw.open_session("s1", attributes={"locale": "en-IN"})  # reconnect updates attrs
    session = gw.get_session("s1")
    assert session is not None
    assert session.metadata.attributes["codec"] == "opus"
    assert session.metadata.attributes["locale"] == "en-IN"
