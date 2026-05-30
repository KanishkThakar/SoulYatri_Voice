"""Phase 5B tests — token stream backpressure, sequencing, cancellation.

Acceptance: token stream stays stable under load and cancellation (no deadlock, prompt
unblock of pending put/get).
"""

from __future__ import annotations

import asyncio

import pytest

from shared.contracts import CodecChunk
from speech.codec.token_stream import (
    SequenceError,
    StreamCancelled,
    TokenStream,
    drain_to_list,
)


def _chunk(seq: int, *, is_final: bool = False) -> CodecChunk:
    return CodecChunk(turn_id="t1", seq=seq, codec_tokens=[seq, seq + 1], is_final=is_final)


def test_produce_consume_in_order():
    async def scenario():
        # maxsize=4 with 5 items: the producer MUST run concurrently with the consumer,
        # otherwise the 5th put blocks forever on the bounded queue (backpressure is real).
        stream = TokenStream(maxsize=4, name="t")

        async def producer():
            for i in range(5):
                await stream.put(_chunk(i, is_final=(i == 4)))

        async def consumer():
            return await drain_to_list(stream)

        _, packets = await asyncio.gather(producer(), consumer())
        return packets

    packets = asyncio.run(scenario())
    assert [p.seq for p in packets] == [0, 1, 2, 3, 4]
    assert packets[-1].is_final is True


def test_backpressure_blocks_producer_until_consumed():
    async def scenario():
        stream = TokenStream(maxsize=2, name="bp")
        # Fill the buffer.
        await stream.put(_chunk(0))
        await stream.put(_chunk(1))
        # Third put must block until a consumer frees a slot.
        put_task = asyncio.ensure_future(stream.put(_chunk(2)))
        await asyncio.sleep(0.01)
        blocked_before = not put_task.done()
        # Consume one -> producer should unblock.
        first = await stream.get()
        await asyncio.wait_for(put_task, timeout=1.0)
        return blocked_before, first.seq, stream.qsize()

    blocked_before, first_seq, _ = asyncio.run(scenario())
    assert blocked_before is True
    assert first_seq == 0


def test_non_monotonic_sequence_rejected():
    async def scenario():
        stream = TokenStream(maxsize=4, enforce_sequence=True)
        await stream.put(_chunk(0))
        await stream.put(_chunk(3))
        await stream.put(_chunk(1))  # regression -> error

    with pytest.raises(SequenceError):
        asyncio.run(scenario())


def test_auto_sequence_assignment():
    async def scenario():
        stream = TokenStream(maxsize=8, enforce_sequence=False)
        # Put chunks with arbitrary seq; the stream re-numbers them.
        await stream.put(_chunk(99))
        await stream.put(_chunk(5))
        await stream.close()
        return await drain_to_list(stream)

    packets = asyncio.run(scenario())
    assert [p.seq for p in packets] == [0, 1]


def test_cancel_unblocks_pending_put():
    async def scenario():
        stream = TokenStream(maxsize=1, name="cancel-put")
        await stream.put(_chunk(0))
        put_task = asyncio.ensure_future(stream.put(_chunk(1)))
        await asyncio.sleep(0.01)
        assert not put_task.done()
        await stream.cancel("test")
        with pytest.raises(StreamCancelled):
            await asyncio.wait_for(put_task, timeout=1.0)
        return stream.stats()

    stats = asyncio.run(scenario())
    assert stats["cancelled"] is True


def test_cancel_unblocks_pending_get():
    async def scenario():
        stream = TokenStream(maxsize=2, name="cancel-get")
        get_task = asyncio.ensure_future(stream.get())
        await asyncio.sleep(0.01)
        assert not get_task.done()
        await stream.cancel("test")
        # A get parked on an empty cancelled stream resolves to None (clean end).
        result = await asyncio.wait_for(get_task, timeout=1.0)
        return result

    result = asyncio.run(scenario())
    assert result is None


def test_cancel_during_iteration_terminates_cleanly():
    async def scenario():
        stream = TokenStream(maxsize=8, name="cancel-iter")
        consumed = []

        async def consumer():
            async for packet in stream:
                consumed.append(packet.seq)

        consumer_task = asyncio.ensure_future(consumer())
        for i in range(3):
            await stream.put(_chunk(i))
        await asyncio.sleep(0.01)
        await stream.cancel("barge_in")
        await asyncio.wait_for(consumer_task, timeout=1.0)
        return consumed

    # Should terminate without deadlock; consumed is a prefix of produced.
    consumed = asyncio.run(scenario())
    assert consumed == sorted(consumed)


def test_stream_under_load_no_loss():
    async def scenario():
        stream = TokenStream(maxsize=4, name="load")
        n = 200

        async def producer():
            for i in range(n):
                await stream.put(_chunk(i, is_final=(i == n - 1)))

        async def consumer():
            out = []
            async for packet in stream:
                out.append(packet.seq)
            return out

        _, consumed = await asyncio.gather(producer(), consumer())
        return consumed, n

    consumed, n = asyncio.run(scenario())
    assert consumed == list(range(n))
