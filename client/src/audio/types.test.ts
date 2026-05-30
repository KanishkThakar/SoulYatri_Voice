/**
 * Unit tests for the DOM-free audio helpers in audio/types.ts (Phase 2A).
 * Capture/transport/playback classes depend on WebAudio and are exercised in the
 * browser; these tests cover the pure conversion/resample logic that backs them.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  AudioFrame,
  frameToPcm16,
  pcm16ToFloat32,
  frameToWire,
  resampleLinear,
} from "./types";

test("pcm16 round-trip preserves samples within quantization error", () => {
  const pcm = new Float32Array([0, 0.5, -0.5, 0.999, -0.999]);
  const frame: AudioFrame = { pcm, tsMs: 1 };
  const bytes = frameToPcm16(frame);
  const back = pcm16ToFloat32(bytes);
  assert.equal(back.length, pcm.length);
  for (let i = 0; i < pcm.length; i++) {
    assert.ok(Math.abs(back[i] - pcm[i]) < 2 / 32767, `sample ${i}`);
  }
});

test("frameToPcm16 clamps out-of-range samples", () => {
  const frame: AudioFrame = { pcm: new Float32Array([2, -2]), tsMs: 0 };
  const back = pcm16ToFloat32(frameToPcm16(frame));
  assert.ok(back[0] <= 1 && back[0] > 0.99);
  assert.ok(back[1] >= -1 && back[1] < -0.99);
});

test("frameToWire fills correlation fields from fallback", () => {
  const frame: AudioFrame = { pcm: new Float32Array([0.1]), tsMs: 42 };
  const wire = frameToWire(frame, { sessionId: "s1", seq: 7, sampleRate: 16000 });
  assert.equal(wire.session_id, "s1");
  assert.equal(wire.seq, 7);
  assert.equal(wire.sample_rate, 16000);
  assert.equal(wire.ts_ms, 42);
  assert.equal(wire.is_final, false);
  assert.equal(wire.pcm.length, 1);
  assert.ok(Math.abs(wire.pcm[0] - 0.1) < 1e-6);
});

test("resampleLinear downsamples 48k -> 16k by ~1/3 length", () => {
  const input = new Float32Array(48000).map((_, i) => Math.sin(i / 10));
  const out = resampleLinear(input, 48000, 16000);
  assert.ok(Math.abs(out.length - 16000) <= 1);
});

test("resampleLinear is identity when rates match", () => {
  const input = new Float32Array([1, 2, 3]);
  assert.equal(resampleLinear(input, 16000, 16000), input);
});
