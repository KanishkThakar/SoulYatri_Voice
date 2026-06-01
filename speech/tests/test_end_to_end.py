"""End-to-end speech-native loop test (Phases 5 -> 6 -> 10).

Exercises the frozen architecture on CPU fallbacks:

    Audio -> Mimi(mock) codec tokens -> Moshi(echo) runtime -> codec tokens
          -> decoder(mock) -> Audio

Confirms the whole loop streams to completion without deadlock and that an interruption
propagates cleanly through runtime cancel + decoder stop.
"""

from __future__ import annotations

import asyncio

from speech.codec._signal import make_frames, sine_pcm
from speech.codec.mimi_bridge import make_codec_bridge
from speech.codec.token_stream import TokenStream
from speech.decoder.service import make_decoder
from speech.moshi_runtime.service import make_runtime
from speech.tokenizer.audio_tokenizer import AudioTokenizer


def test_full_loop_streams_to_completion():
    async def scenario():
        bridge = make_codec_bridge(backend="mock")
        tokenizer = AudioTokenizer(bridge=bridge)
        runtime = make_runtime(backend="echo", max_reply_chunks=4)
        decoder = make_decoder(bridge=bridge)

        # 1) Audio -> codec tokens (user turn).
        pcm = sine_pcm(int(bridge.sample_rate * 0.4), freq=210.0, sample_rate=bridge.sample_rate)
        frames = make_frames(pcm, frame_samples=480, sample_rate=bridge.sample_rate)
        user_chunks = list(tokenizer.tokenize(frames))
        assert user_chunks

        async def user_stream():
            for c in user_chunks:
                yield c

        # 2) codec tokens -> runtime -> reply codec tokens.
        reply_chunks = []
        async for reply in runtime.stream_reply("e2e", user_stream()):
            reply_chunks.append(reply)
        assert reply_chunks
        assert reply_chunks[-1].is_final is True

        # 3) reply codec tokens -> decoder -> audio.
        async def reply_stream():
            for c in reply_chunks:
                yield c

        audio_out = []
        async for frame in decoder.stream_decode(reply_stream(), session_id="e2e"):
            audio_out.append(frame)
        return user_chunks, reply_chunks, audio_out

    user_chunks, reply_chunks, audio_out = asyncio.run(scenario())
    assert audio_out, "expected reconstructed audio frames"
    assert audio_out[-1].is_final is True
    # All audio frames carry PCM at the codec rate.
    assert all(f.sample_rate == 24000 for f in audio_out)


def test_full_loop_with_token_stream_transport():
    # Pipe the runtime's reply through the bounded TokenStream (backpressure) before decode.
    async def scenario():
        bridge = make_codec_bridge(backend="mock")
        runtime = make_runtime(backend="echo", max_reply_chunks=4)
        decoder = make_decoder(bridge=bridge)
        stream = TokenStream(maxsize=2, name="e2e-transport", enforce_sequence=False)

        async def user_stream():
            from shared.contracts import CodecChunk

            for i in range(3):
                yield CodecChunk(turn_id="e2e2", seq=i, codec_tokens=[500 + i] * 480,
                                 is_final=(i == 2))

        async def produce():
            async for reply in runtime.stream_reply("e2e2", user_stream()):
                await stream.put(reply.model_copy(update={"is_final": False}))
            await stream.close()

        async def consume():
            out = []

            async def chunk_iter():
                async for packet in stream:
                    yield packet.chunk

            async for frame in decoder.stream_decode(chunk_iter(), session_id="e2e2"):
                out.append(frame)
            return out

        _, audio = await asyncio.gather(produce(), consume())
        return audio

    audio = asyncio.run(scenario())
    assert audio, "expected audio through the bounded transport"


def test_interruption_propagates_through_loop():
    async def scenario():
        bridge = make_codec_bridge(backend="mock")
        runtime = make_runtime(backend="echo", max_reply_chunks=50)
        decoder = make_decoder(bridge=bridge)
        turn_id = "e2e3-t1"

        from shared.contracts import CodecChunk

        async def user_stream():
            for i in range(3):
                yield CodecChunk(turn_id=turn_id, seq=i, codec_tokens=[700 + i] * 600,
                                 is_final=(i == 2))

        produced = []

        async def run_turn():
            agen = runtime.stream_reply("e2e3", user_stream())
            async for reply in agen:
                produced.append(reply)
                # After the first reply chunk decodes, barge in.
                async for _frame in decoder.stream_decode(_single(reply), session_id="e2e3"):
                    pass
                if len(produced) == 1:
                    await runtime.cancel("e2e3", turn_id)
                    decoder.interrupt([0.5] * 480)

        async def _single(chunk):
            yield chunk

        await asyncio.wait_for(run_turn(), timeout=3.0)
        control = runtime.repair.get("e2e3", turn_id)
        return produced, control, decoder

    produced, control, decoder = asyncio.run(scenario())
    assert control is not None
    assert control.cancelled is True
    assert decoder.interruption.interrupted is True
    # Cancellation stopped generation early relative to the 50-chunk cap.
    assert len(produced) < 50
