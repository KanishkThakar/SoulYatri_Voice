"""Phase 6 tests — runtime streaming + cancel + continuity + repair.

Acceptance: a short turn streams to completion without deadlock; interruption leads to a
clean stop and recoverable continuation. All on the echo CPU fallback (no weights).
"""

from __future__ import annotations

import asyncio

from shared.contracts import CodecChunk, EmotionState, PersonaState
from speech.moshi_runtime.repair import RepairAction
from speech.moshi_runtime.service import MoshiRuntimeService, make_runtime


def _runtime() -> MoshiRuntimeService:
    return make_runtime(backend="echo", max_reply_chunks=5)


async def _user_turn(turn_id: str, n: int = 3):
    for i in range(n):
        yield CodecChunk(
            turn_id=turn_id,
            seq=i,
            codec_tokens=[1000 + i] * 600,
            is_final=(i == n - 1),
        )


def test_runtime_selects_echo_without_weights():
    rt = make_runtime(backend="auto")
    assert rt.backend_name == "echo_transform"
    assert rt.is_real_backend is False


def test_short_turn_streams_to_completion():
    async def scenario():
        rt = _runtime()
        out = []
        async for chunk in rt.stream_reply("s1", _user_turn("s1-t1")):
            out.append(chunk)
        return out, rt

    out, rt = asyncio.run(scenario())
    assert out, "expected a non-empty reply stream"
    assert out[-1].is_final is True
    assert [c.seq for c in out] == list(range(len(out)))
    # Continuity: the turn is recorded and no longer active.
    state = rt.sessions.get("s1")
    assert state is not None
    assert state.turn_counter == 1
    assert state.active_turn_id is None


def test_empty_input_stream_still_terminates():
    async def empty():
        if False:  # pragma: no cover - never yields
            yield  # type: ignore

    async def scenario():
        rt = _runtime()
        out = []
        async for chunk in rt.stream_reply("s-empty", empty()):
            out.append(chunk)
        return out

    out = asyncio.run(scenario())
    assert out, "even an empty turn yields a bounded neutral reply"
    assert out[-1].is_final is True


def test_cancel_midstream_stops_cleanly_and_is_recoverable():
    async def scenario():
        rt = make_runtime(backend="echo", max_reply_chunks=50)
        received = []
        turn_id = "s2-t1"

        agen = rt.stream_reply("s2", _user_turn(turn_id, n=4))
        # Pull the first chunk, then cancel mid-stream.
        first = await agen.__anext__()
        received.append(first)
        await rt.cancel("s2", turn_id)
        # Drain the rest; generation must stop promptly without deadlock.
        async for chunk in agen:
            received.append(chunk)

        control = rt.repair.get("s2", turn_id)
        cont = rt.repair.continuation_point("s2", turn_id)
        return received, control, cont

    received, control, cont = asyncio.run(scenario())
    assert len(received) >= 1
    assert control is not None
    assert control.cancelled is True
    # Rollback was recorded during the finally block.
    assert control.action in (RepairAction.rolled_back, RepairAction.continued)
    # Interruption-aware continuation is resumable and reports what was heard.
    assert cont["resumable"] is True
    assert cont["chunks_already_heard"] == control.emitted_chunks


def test_cancel_via_token_stream_no_deadlock_under_timeout():
    async def scenario():
        rt = make_runtime(backend="echo", max_reply_chunks=100)
        turn_id = "s3-t1"
        agen = rt.stream_reply("s3", _user_turn(turn_id, n=2))

        async def consume():
            seen = 0
            async for _chunk in agen:
                seen += 1
                if seen == 1:
                    await rt.cancel("s3", turn_id)
            return seen

        # Whole thing must finish well within the timeout (no deadlock).
        return await asyncio.wait_for(consume(), timeout=2.0)

    seen = asyncio.run(scenario())
    assert seen >= 1


def test_session_continuity_across_turns():
    async def scenario():
        rt = _runtime()
        persona = PersonaState(persona_id="soulyatri", language="hinglish")
        rt.set_persona("s4", persona)
        state = rt.sessions.get_or_create("s4")
        state.push_emotion(EmotionState(valence=0.5, warmth=0.9))

        # Two successive turns.
        async for _ in rt.stream_reply("s4", _user_turn("s4-t1")):
            pass
        async for _ in rt.stream_reply("s4", _user_turn("s4-t2")):
            pass
        return rt.session_context("s4")

    ctx = asyncio.run(scenario())
    assert ctx["n_turns"] == 2
    assert ctx["persona_id"] == "soulyatri"
    assert ctx["language"] == "hinglish"
    # Recent emotion carries the warmth we pushed.
    assert ctx["recent_emotion"]["warmth"] > 0.5


def test_restart_supersedes_cancelled_turn():
    rt = _runtime()
    rt.repair.register("s5", "s5-t1")
    rt.repair.cancel("s5", "s5-t1")
    new_control = rt.repair.restart("s5", "s5-t1", "s5-t2")
    old = rt.repair.get("s5", "s5-t1")
    assert old is not None and old.superseded_by == "s5-t2"
    assert old.action == RepairAction.restarted
    assert new_control.turn_id == "s5-t2"
    assert new_control.cancelled is False
