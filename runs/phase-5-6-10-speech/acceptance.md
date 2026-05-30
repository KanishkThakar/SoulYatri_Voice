# Acceptance — Phases 5 / 6 / 10: Speech-native codec, runtime, and decoder

**Task:** Verify and finalize the speech subsystem (`final_use.md` Phases 5, 6, 10 — Mimi
codec bridge + token-stream abstraction, Moshi runtime shell, fast acoustic decoder +
interruption control). The implementation already existed under `speech/`; the test suite
**deadlocked**. This record documents the root-cause fix, the green verification run, and
the acceptance-criteria mapping.

**Environment:** Windows, Python 3.11.9, pytest 9.0.2, `pytest-timeout` installed, ruff
0.15.10, pydantic 2.x. CPU-only, no GPU, **no Moshi/Mimi/torch weights**. Heavy backends
stay lazy-loaded behind interfaces with deterministic CPU fallbacks
(`MockCodecBackend`, `EchoTransformBackend`) selected automatically when weights are absent.

**File ownership (respected):** changes were confined to the `speech/` folder and this
acceptance note. `shared/`, `docs/`, `pyproject.toml`, `server/`, and all other domains were
**not** modified. `CodecChunk`, `AudioFrame`, `EmotionState`, `PersonaState` continue to be
imported from `shared.contracts` (never redefined).

---

## 1. Phase 5/6/10 modules present (audited, not rewritten)

### Phase 5 — Neural codec bridge + token stream (`speech/codec/`, `speech/tokenizer/`)
```text
speech/codec/mimi_bridge.py     # MimiCodecBridge + MockCodecBackend / MimiBackend (lazy);
                                #   encode/decode roundtrip behind the CodecBridge protocol.
speech/codec/token_stream.py    # TokenStream (bounded async queue), TokenPacket,
                                #   StreamCancelled, SequenceError — backpressure + sequencing
                                #   + timestamps + cancellation + end sentinel.
speech/codec/benchmark.py       # run_benchmark — codec latency / boundary / jitter report.
speech/codec/_compat.py         # CPU-safe logger + CodecBridge protocol shim (no torch/moshi).
speech/codec/_signal.py,_dsp.py # pure-Python signal/DSP helpers for tests + mock codec.
speech/tokenizer/audio_tokenizer.py  # AudioTokenizer — AudioFrame -> CodecChunk wrapper.
```

### Phase 6 — Moshi runtime shell (`speech/moshi_runtime/`)
```text
speech/moshi_runtime/service.py          # MoshiRuntimeService + EchoTransformBackend /
                                         #   MoshiBackend (lazy); implements SpeechRuntime
                                         #   (stream_reply / cancel) from INTERFACES §5.1.
speech/moshi_runtime/session_runtime.py  # SessionStore / SessionState / TurnRecord —
                                         #   cross-turn continuity (speaker + recent emotion).
speech/moshi_runtime/repair.py           # RepairController / TurnControl / RepairAction —
                                         #   cancel, rollback, restart, resumable continuation.
```

### Phase 10 — Fast decoder + interruption (`speech/decoder/`)
```text
speech/decoder/service.py        # DecoderService + DecoderRequest/DecoderConfig + LRU cache;
                                 #   stream_decode (first-chunk-fast) and decode_all.
speech/decoder/waveform.py       # WaveformJoiner — chunk decode + crossfade smooth joins.
speech/decoder/interruption.py   # PlaybackInterruptionController / StopPolicy /
                                 #   InterruptionResult — fade vs hard-cut within budget.
```

Tests live under `speech/tests/` (codec roundtrip, token stream, runtime streaming, decoder
interruption, end-to-end loop) and `speech/persona/tests/` (Phase 9, already accepted).

---

## 2. Deadlock root cause + fix

**Symptom:** `python -m pytest speech` hung indefinitely (no progress, no completion).

**Root cause:** `speech/tests/test_token_stream.py::test_produce_consume_in_order`.
The test created `TokenStream(maxsize=4)` and then, in a **single coroutine with no
concurrent consumer**, issued 5 sequential `await stream.put(...)` calls:

```python
stream = TokenStream(maxsize=4, name="t")
for i in range(5):
    await stream.put(_chunk(i, is_final=(i == 4)))   # 5th put blocks forever
packets = await drain_to_list(stream)                # never reached
```

`TokenStream.put` implements **real backpressure**: it `await`s on a bounded
`asyncio.Queue(maxsize=4)`, so once 4 packets are buffered the 5th `put` blocks until a
consumer frees a slot. Because `drain_to_list` (the only consumer) was scheduled *after*
the loop, the 5th `put` could never be relieved → permanent deadlock, which froze the whole
`pytest speech` run.

**Diagnosis: the implementation is correct; the test was wrong.** Backpressure that blocks a
producer when the buffer is full is exactly the Phase 5B contract ("a slow consumer throttles
a fast producer"). The test violated that contract by producing more than `maxsize` items with
no concurrent drain.

**Fix (test-only, honoring backpressure):** run the producer and consumer **concurrently**
via `asyncio.gather`, the same pattern already used by the passing `test_stream_under_load_no_loss`.
The test's intent (in-order delivery `[0,1,2,3,4]` and final-flag on the last packet) is fully
preserved; no assertions were weakened.

```python
def test_produce_consume_in_order():
    async def scenario():
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
```

**Audit of the other async tests** (for the same "produce-beyond-maxsize-without-consumer"
pattern): all other deadlock-sensitive tests were already correct and were left unchanged:
- `test_stream_under_load_no_loss` — already uses `asyncio.gather(producer(), consumer())` (200 items, maxsize=4).
- `test_backpressure_blocks_producer_until_consumed` — intentionally asserts the 3rd put blocks, then consumes to unblock with `wait_for`.
- `test_cancel_unblocks_pending_put` / `_get`, `test_cancel_during_iteration_terminates_cleanly` — exercise cancellation, guarded by `wait_for` timeouts.
- `test_full_loop_with_token_stream_transport` (end-to-end, maxsize=2) — already gathers producer + consumer.
- All runtime/decoder/e2e async tests bound themselves with `asyncio.wait_for(...)`.

No other deadlock-pattern tests were found, so only the one test was changed.

**In-scope lint cleanups (no behavior change):** to keep the `ruff check speech` gate fully
green, three pre-existing nits inside `speech/` were fixed surgically:
- `speech/codec/benchmark.py` — `B007`: unused loop var `packet` → `_packet`.
- `speech/codec/_compat.py` — `UP037`: removed quotes from a self-referential return annotation (`"_StdlibStructShim"` → `_StdlibStructShim`; file has `from __future__ import annotations`).
- `speech/decoder/service.py` — `UP037`: removed quotes from `OrderedDict[...]` annotation.

### Files changed
```text
speech/tests/test_token_stream.py   # deadlock fix: concurrent producer/consumer (test bug)
speech/codec/benchmark.py           # ruff B007 (unused loop var rename)
speech/codec/_compat.py             # ruff UP037 (drop quotes on annotation)
speech/decoder/service.py           # ruff UP037 (drop quotes on annotation)
runs/phase-5-6-10-speech/acceptance.md   # this record
```
No production logic in the codec/runtime/decoder paths was altered; the backpressure,
cancellation, and lazy-load behavior is exactly as implemented.

---

## 3. Verification commands + final output

```text
# 1. Reproduce the deadlock (pre-fix) — fails fast via pytest-timeout
python -m pytest speech/tests/test_token_stream.py::test_produce_consume_in_order -q -p no:cacheprovider --timeout=15
→ +++ Timeout +++  (stack parked in TokenStream.put on the bounded queue)   exit 1

# 2. Full speech suite, deadlock guard armed (post-fix)
python -m pytest speech -q -p no:cacheprovider --timeout=60
→ 72 passed in 0.56s        exit 0      (no timeouts, no skips, no warnings)

# 3. CPU import smoke test (no GPU / no Moshi/Mimi weights at import)
python -c "import speech.codec.mimi_bridge, speech.codec.token_stream, speech.moshi_runtime.service, speech.decoder.service, speech.tokenizer.audio_tokenizer"
→ CPU imports OK            exit 0

# 4. Lint
python -m ruff check speech
→ All checks passed!        exit 0
```

**Result: deadlock-free and green.** 72 tests pass under a 60s-per-test timeout; clean CPU
imports; ruff clean.

---

## 4. Definition of Done (final_use.md §3.3)
- [x] **code** — Phase 5/6/10 modules present and verified (audited, minimally fixed).
- [x] **tests** — 72 pytest cases across `speech/` pass with no deadlock under `--timeout=60`.
- [x] **design note** — module design notes already in each file's docstring + `speech/persona/README.md`; this record documents the fix.
- [x] **structured logging hooks** — `speech/codec/_compat.get_logger` (structlog → stdlib fallback); events e.g. `token_stream_cancelled`, `token_stream_iter_cancelled`.
- [x] **benchmark note** — `speech/codec/benchmark.py::run_benchmark` (latency / boundary stability / jitter), exercised by `test_benchmark_report_structure_and_bounds`.
- [x] **acceptance result recorded** — this file under `runs/`.

---

## 5. Acceptance-criteria mapping (final_use.md Phases 5 / 6 / 10)

### Phase 5A — codec integration → *"roundtrip audio remains intelligible"*
- `test_roundtrip_is_recoverable` — roundtrip error < 1e-3 on the mock backend (16-bit grid).
- `test_roundtrip_preserves_energy` — input/output RMS within 5%.
- `test_resample_roundtrip_16k_to_24k` — 16 kHz capture survives the 24 kHz codec.
- `test_bridge_selects_mock_without_weights` — `auto` backend falls back to `mock` (no weights), `is_real_backend is False` (lazy-load guard).

### Phase 5B — token stream → *"token stream remains stable under load and cancellation"*
- `test_produce_consume_in_order` — **(fixed)** in-order `[0..4]` + final flag, honoring backpressure.
- `test_backpressure_blocks_producer_until_consumed` — producer blocks when full, unblocks on consume.
- `test_stream_under_load_no_loss` — 200 items through maxsize=4, zero loss, order preserved.
- `test_non_monotonic_sequence_rejected` / `test_auto_sequence_assignment` — sequencing contract.
- `test_cancel_unblocks_pending_put` / `_get` / `test_cancel_during_iteration_terminates_cleanly` — prompt cancellation, no deadlock.

### Phase 5C — benchmark codec path → *"within budget, no unexplained latency spikes"*
- `test_benchmark_report_structure_and_bounds` — TTFC ≥ 0, ≥1 chunk, boundaries uniform/stable, jitter shows no loss + order preserved.

### Phase 6A/6B/6C — Moshi runtime → *"answers a short turn without deadlock; continuity; clean stop + recoverable continuation"*
- `test_short_turn_streams_to_completion` — bounded reply stream, monotonic seq, turn recorded, no active turn left dangling.
- `test_empty_input_stream_still_terminates` — even an empty turn yields a bounded neutral reply (no hang).
- `test_session_continuity_across_turns` — persona/emotion/turn-count carried across two turns (6B).
- `test_cancel_midstream_stops_cleanly_and_is_recoverable` + `test_cancel_via_token_stream_no_deadlock_under_timeout` — cancel stops promptly under `wait_for`; rollback recorded; continuation is resumable (6C repair).
- `test_restart_supersedes_cancelled_turn` — restart supersedes the cancelled turn (`RepairAction.restarted`).
- `test_runtime_selects_echo_without_weights` — `auto` → `echo_transform` fallback, `is_real_backend is False`.

### Phase 10A/10B/10C — decoder + interruption → *"first chunk fast; smooth joins; stops within budget"*
- `test_streaming_first_chunk_fast_and_complete` — first playable frame emitted before the whole turn decodes (≥2 frames, final flag set).
- `test_decode_all_smooth_join_no_huge_artifact` + `test_waveform_joiner_crossfade_continuity` — joins bounded (peak ≤ 1.01, max step < 0.2), no artifacts (10B).
- `test_cache_hit_on_repeated_chunk` — bounded LRU short-circuits repeat decodes (10A cache policy).
- `test_streaming_stops_on_interruption` — barge-in stops decode early (fewer frames than input), within budget.
- `test_interruption_fade_within_budget` / `test_interruption_hard_cut_discards_all` — fade ends at ~0 amplitude; hard-cut flushes all; both within stop budget (10C).

### End-to-end (Phases 5 → 6 → 10 integration)
- `test_full_loop_streams_to_completion` — Audio → Mimi(mock) tokens → Moshi(echo) → decoder(mock) → Audio streams to completion (24 kHz frames, final flag).
- `test_full_loop_with_token_stream_transport` — reply piped through bounded `TokenStream` (maxsize=2) with concurrent produce/consume.
- `test_interruption_propagates_through_loop` — barge-in propagates through runtime `cancel` + decoder `interrupt`; generation stops early; control marked cancelled.

---

## 6. CPU / no-weights guarantee
- `make_codec_bridge(backend="auto")` and `make_runtime(backend="auto")` select the mock /
  echo CPU fallbacks when no weights are present — confirmed by
  `test_bridge_selects_mock_without_weights` and `test_runtime_selects_echo_without_weights`.
- `speech/codec/_compat.py` is the only outward dependency and imports no torch/moshi/mimi at
  module top level; the import smoke test (command 3) passes with exit 0.
- Heavy backends (`MimiBackend`, `MoshiBackend`) remain lazy-loaded behind their interfaces —
  left unchanged by this verification pass.
