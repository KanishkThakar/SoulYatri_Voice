/**
 * Unit tests for the filler engine (Phase 3C).
 *
 * Verifies the acceptance criteria: filler triggers are deterministic,
 * cancellable, and do NOT override complex turns (handoff fades the sponge so
 * the real answer is never talked over). A fake player avoids any DOM/AudioContext.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { PhraseBank, PhraseRecord } from "./phrase_schema";
import { FillerEngine } from "./filler_engine";
import { RouteDecision } from "./intent_router";
import type { StreamPlayer } from "../playback/stream_player";
import seed from "./phrase_bank.json";

/** Records calls so tests can assert behavior without WebAudio. */
class FakePlayer {
  calls: string[] = [];
  beginTurn() {
    this.calls.push("beginTurn");
  }
  enqueue() {
    this.calls.push("enqueue");
  }
  enqueuePcm16() {
    this.calls.push("enqueuePcm16");
  }
  async fadeOut() {
    this.calls.push("fadeOut");
  }
  hardStop() {
    this.calls.push("hardStop");
  }
}

function setup(opts: { enabled?: boolean } = {}) {
  const bank = PhraseBank.fromJSON(seed as { phrases: Partial<PhraseRecord>[] });
  const player = new FakePlayer();
  const engine = new FillerEngine({
    player: player as unknown as StreamPlayer,
    phraseBank: bank,
    enabled: opts.enabled ?? true,
    audioLoader: async () => new Float32Array(2400), // 0.1s of silence
  });
  return { bank, player, engine };
}

const trivial: RouteDecision = {
  route: "cached_filler",
  phraseId: "ack_en_001",
  intent: "acknowledgment",
  confidence: 0.75,
  reason: "ack",
  emitFillerThenForward: false,
};

const complex: RouteDecision = {
  route: "full_stack",
  phraseId: "stall_en_001",
  intent: "complex",
  confidence: 0,
  reason: "complex",
  emitFillerThenForward: true,
};

test("plan is deterministic for the same decision", () => {
  const { engine } = setup();
  assert.deepEqual(engine.plan(trivial), engine.plan(trivial));
  assert.deepEqual(engine.plan(complex), engine.plan(complex));
});

test("trivial turn yields immediate action, no handoff", () => {
  const { engine } = setup();
  const plan = engine.plan(trivial);
  assert.equal(plan.action, "immediate");
  assert.equal(plan.expectsHandoff, false);
});

test("complex turn yields latency_sponge expecting handoff", () => {
  const { engine } = setup();
  const plan = engine.plan(complex);
  assert.equal(plan.action, "latency_sponge");
  assert.equal(plan.expectsHandoff, true);
});

test("disable switch makes engine a no-op", async () => {
  const { engine, player } = setup({ enabled: false });
  const plan = engine.plan(trivial);
  assert.equal(plan.action, "skipped");
  const res = await engine.play(trivial);
  assert.equal(res.played, false);
  assert.ok(!player.calls.includes("enqueue"));
});

test("play schedules audio for a safe trivial phrase", async () => {
  const { engine, player } = setup();
  const res = await engine.play(trivial);
  assert.equal(res.played, true);
  assert.ok(player.calls.includes("beginTurn"));
  assert.ok(player.calls.includes("enqueue"));
});

test("handoff fades a latency sponge so complex turn is not overridden", async () => {
  const { engine, player } = setup();
  await engine.play(complex);
  const handed = await engine.handoffToMain();
  assert.equal(handed, true);
  assert.ok(player.calls.includes("fadeOut"));
  assert.equal(engine.activeFillerId, null);
});

test("handoff is a no-op for a trivial (immediate) filler", async () => {
  const { engine } = setup();
  await engine.play(trivial);
  const handed = await engine.handoffToMain();
  assert.equal(handed, false); // trivial filler IS the answer; nothing to hand off
});

test("cancel hard-stops an active filler", async () => {
  const { engine, player } = setup();
  await engine.play(complex);
  engine.cancel("hard");
  assert.ok(player.calls.includes("hardStop"));
  assert.equal(engine.activeFillerId, null);
});

test("unsafe phrase is never played", async () => {
  const bank = new PhraseBank([
    {
      id: "unsafe1",
      text: "x",
      transcript: "x",
      audioPath: "x.opus",
      language: "en",
      tone: "neutral",
      intent: "acknowledgment",
      emotion: "calm",
      category: "acknowledgment",
      duration: 0.3,
      confidence: 0.7,
      priority: 1,
      safetyTag: "needs_review",
    },
  ]);
  const player = new FakePlayer();
  const engine = new FillerEngine({
    player: player as unknown as StreamPlayer,
    phraseBank: bank,
    audioLoader: async () => new Float32Array(10),
  });
  const decision: RouteDecision = {
    route: "cached_filler",
    phraseId: "unsafe1",
    intent: "acknowledgment",
    confidence: 0.7,
    reason: "ack",
    emitFillerThenForward: false,
  };
  const plan = engine.plan(decision);
  assert.equal(plan.action, "skipped");
  const res = await engine.play(decision);
  assert.equal(res.played, false);
});
