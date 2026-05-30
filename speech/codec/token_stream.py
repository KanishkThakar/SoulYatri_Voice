"""
speech/codec/token_stream.py — Phase 5B: token-stream abstraction over CodecChunk.
==================================================================================

Design note (Phase 5B, final_use.md §Phase-5 / docs/INTERFACES.md §1.2 & §5)
----------------------------------------------------------------------------
The codec bridge turns audio into ``CodecChunk``s. The *stream* layer adds the runtime
properties a streaming speech system needs:

* **Backpressure** — a bounded async queue (``maxsize``) so a slow consumer throttles a
  fast producer instead of blowing up memory. Producers ``await put`` and naturally block
  when the buffer is full.
* **Sequencing** — packets carry a monotonic ``seq`` that is validated/auto-assigned, so
  out-of-order or duplicated chunks are detected.
* **Timestamps** — every packet keeps the ``CodecChunk.ts_ms`` and also records an
  arrival monotonic time for jitter measurement.
* **Cancellation** — a stream can be cancelled cooperatively; ``put`` and ``get`` raise
  ``StreamCancelled`` promptly so turns can be interrupted (barge-in) without deadlock.
* **Termination** — an explicit end-of-stream sentinel (``is_final`` chunk or ``close``)
  lets consumers iterate to completion with ``async for``.

This is the queue/transport contract that ``speech/moshi_runtime`` and ``speech/decoder``
consume. It deliberately holds ``CodecChunk`` (the shared contract) rather than inventing
a new wire type — ``TokenPacket`` only *wraps* a chunk with stream-local metadata.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field

from ._compat import CodecChunk, get_logger

log = get_logger(__name__)

__all__ = [
    "StreamCancelled",
    "SequenceError",
    "TokenPacket",
    "TokenStream",
    "drain_to_list",
]


class StreamCancelled(Exception):
    """Raised by stream operations when the stream has been cancelled."""


class SequenceError(Exception):
    """Raised when a chunk arrives with an unexpected (non-monotonic) sequence number."""


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


@dataclass
class TokenPacket:
    """A ``CodecChunk`` plus stream-local metadata (Phase 5B token packet type).

    ``arrival_ms`` is a monotonic timestamp captured when the packet entered the stream;
    it is used for jitter measurement and is independent of the wall-clock ``chunk.ts_ms``.
    """

    chunk: CodecChunk
    arrival_ms: int = field(default_factory=_monotonic_ms)

    @property
    def seq(self) -> int:
        return self.chunk.seq

    @property
    def is_final(self) -> bool:
        return self.chunk.is_final

    @property
    def ts_ms(self) -> int:
        return self.chunk.ts_ms


class TokenStream:
    """A bounded, cancellable async stream of :class:`TokenPacket`.

    Usage (producer/consumer)::

        stream = TokenStream(maxsize=8, name="turn-1")
        # producer
        await stream.put(chunk)
        await stream.close()          # or send a chunk with is_final=True
        # consumer
        async for packet in stream:
            ...

    Cancellation::

        await stream.cancel()         # unblocks pending put/get with StreamCancelled

    Parameters
    ----------
    maxsize:
        Backpressure bound. ``put`` blocks once this many packets are buffered. Must be
        >= 1. Defaults to 16.
    name:
        Identifier for logging (typically the ``turn_id``).
    enforce_sequence:
        When True (default), ``put`` validates that ``chunk.seq`` is strictly increasing,
        raising :class:`SequenceError` otherwise. When False, sequence is auto-assigned.
    """

    def __init__(
        self,
        maxsize: int = 16,
        *,
        name: str = "token-stream",
        enforce_sequence: bool = True,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1 for backpressure to work")
        self.name = name
        self.maxsize = maxsize
        self.enforce_sequence = enforce_sequence
        self._queue: asyncio.Queue[TokenPacket | None] = asyncio.Queue(maxsize=maxsize)
        self._cancelled = asyncio.Event()
        self._closed = False
        self._last_seq = -1
        self._next_seq = 0
        # observability counters
        self.produced = 0
        self.consumed = 0
        self.dropped = 0

    # -- state -------------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def closed(self) -> bool:
        return self._closed

    def qsize(self) -> int:
        return self._queue.qsize()

    # -- producer side -----------------------------------------------------
    async def put(self, chunk: CodecChunk) -> None:
        """Enqueue a chunk, blocking (backpressure) when the buffer is full.

        Raises :class:`StreamCancelled` if the stream is cancelled while waiting, and
        :class:`SequenceError` if ``enforce_sequence`` and the sequence regresses.
        """
        if self._cancelled.is_set():
            raise StreamCancelled(f"stream {self.name!r} cancelled")
        if self._closed:
            raise RuntimeError(f"cannot put on closed stream {self.name!r}")

        if self.enforce_sequence:
            if chunk.seq <= self._last_seq:
                raise SequenceError(
                    f"non-monotonic seq on {self.name!r}: got {chunk.seq}, last {self._last_seq}"
                )
        else:
            chunk = chunk.model_copy(update={"seq": self._next_seq})
        self._last_seq = chunk.seq
        self._next_seq = chunk.seq + 1

        packet = TokenPacket(chunk=chunk)
        await self._race_cancel(self._queue.put(packet), op="put")
        self.produced += 1
        if chunk.is_final:
            self._closed = True
            await self._race_cancel(self._queue.put(None), op="put-sentinel")

    async def put_many(self, chunks: Iterable[CodecChunk]) -> None:
        """Convenience: put a batch of chunks respecting backpressure + cancellation."""
        for chunk in chunks:
            await self.put(chunk)

    async def close(self) -> None:
        """Signal end-of-stream so consumers terminate cleanly (idempotent)."""
        if self._closed or self._cancelled.is_set():
            return
        self._closed = True
        await self._race_cancel(self._queue.put(None), op="close")

    # -- consumer side -----------------------------------------------------
    async def get(self) -> TokenPacket | None:
        """Dequeue the next packet, or ``None`` at end-of-stream.

        Raises :class:`StreamCancelled` if cancelled while waiting.
        """
        if self._cancelled.is_set() and self._queue.empty():
            raise StreamCancelled(f"stream {self.name!r} cancelled")
        packet = await self._race_cancel(self._queue.get(), op="get")
        if packet is None:
            return None
        self.consumed += 1
        return packet

    def __aiter__(self) -> AsyncIterator[TokenPacket]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[TokenPacket]:
        while True:
            try:
                packet = await self.get()
            except StreamCancelled:
                log.info("token_stream_iter_cancelled", name=self.name, consumed=self.consumed)
                return
            if packet is None:
                return
            yield packet

    # -- cancellation ------------------------------------------------------
    async def cancel(self, reason: str = "cancelled") -> None:
        """Cancel the stream: unblock pending put/get and drop buffered packets."""
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        # Drain to release any producer blocked on a full queue and count drops.
        drained = 0
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is not None:
                drained += 1
        self.dropped += drained
        # Wake any waiter parked on an empty queue.
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:  # pragma: no cover - best effort wakeup
            pass
        log.info("token_stream_cancelled", name=self.name, reason=reason, dropped=self.dropped)

    async def _race_cancel(self, coro, *, op: str):  # noqa: ANN001, ANN202
        """Await ``coro`` but abort promptly if the stream is cancelled."""
        queue_task = asyncio.ensure_future(coro)
        cancel_task = asyncio.ensure_future(self._cancelled.wait())
        try:
            done, pending = await asyncio.wait(
                {queue_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            queue_task.cancel()
            cancel_task.cancel()
            raise
        if cancel_task in done and queue_task not in done:
            queue_task.cancel()
            raise StreamCancelled(f"stream {self.name!r} cancelled during {op}")
        cancel_task.cancel()
        return queue_task.result()

    # -- metrics -----------------------------------------------------------
    def stats(self) -> dict:
        """Snapshot of stream counters for observability/benchmarks."""
        return {
            "name": self.name,
            "produced": self.produced,
            "consumed": self.consumed,
            "dropped": self.dropped,
            "buffered": self.qsize(),
            "cancelled": self.cancelled,
            "closed": self.closed,
        }


async def drain_to_list(stream: TokenStream) -> list[TokenPacket]:
    """Consume a stream fully into a list (test/benchmark helper)."""
    out: list[TokenPacket] = []
    async for packet in stream:
        out.append(packet)
    return out
