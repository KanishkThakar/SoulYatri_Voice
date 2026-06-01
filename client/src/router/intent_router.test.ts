/**
 * Unit tests for the local intent router (Phase 3B).
 *
 * Verifies the acceptance criterion: greetings/acknowledgements route to cached
 * paths, complex turns escalate to full_stack, and low ASR confidence prevents
 * false positives.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { PhraseBank, PhraseRecord } from "./phrase_schema";
import { IntentRouter, IntentKeywords, NullKeywordRecognizer } from "./intent_router";
import seed from "./phrase_bank.json";

function makeRouter(threshold = 0.6): IntentRouter {
  const bank = PhraseBank.fromJSON(seed as { phrases: Partial<PhraseRecord>[] });
  return new IntentRouter({
    phraseBank: bank,
    intentKeywords: seed.intent_keywords as IntentKeywords,
    defaultLanguage: "en",
    cacheConfidenceThreshold: threshold,
  });
}

test("greeting routes to cached_filler", () => {
  const router = makeRouter();
  const d = router.classifyText("hello", { language: "en" });
  assert.equal(d.route, "cached_filler");
  assert.equal(d.intent, "greeting");
  assert.ok(d.phraseId);
  assert.ok(d.confidence >= 0.6);
});

test("acknowledgement routes to cached_filler", () => {
  const router = makeRouter();
  // "mhm" is an acknowledgment-only keyword (not in the confirmation list).
  const d = router.classifyText("mhm", { language: "en" });
  assert.equal(d.route, "cached_filler");
  assert.equal(d.intent, "acknowledgment");
});

test("complex turn escalates to full_stack with latency sponge", () => {
  const router = makeRouter();
  const d = router.classifyText(
    "can you explain how a transformer attention mechanism works in detail",
    { language: "en" }
  );
  assert.equal(d.route, "full_stack");
  assert.equal(d.intent, "complex");
  assert.equal(d.emitFillerThenForward, true);
  assert.ok(d.phraseId, "should attach a stall phrase id");
});

test("low ASR confidence prevents false-positive cached routing", () => {
  const router = makeRouter(0.6);
  // 'hello' matches greeting (base 0.85) but ASR confidence 0.3 → 0.255 < 0.6.
  const d = router.classifyText("hello", { language: "en", asrConfidence: 0.3 });
  assert.equal(d.route, "full_stack");
});

test("emotional distress emits empathy filler then forwards", () => {
  const router = makeRouter();
  const d = router.classifyText("i feel terrible today", {
    language: "en",
    emotion: "sad",
  });
  assert.equal(d.intent, "emotional");
  assert.equal(d.emitFillerThenForward, true);
});

test("classification is deterministic", () => {
  const router = makeRouter();
  const a = router.classifyText("hello there", { language: "en" });
  const b = router.classifyText("hello there", { language: "en" });
  assert.deepEqual(a, b);
});

test("classifyAudio with null recognizer yields silent_wait", async () => {
  const router = makeRouter();
  const d = await router.classifyAudio(new Float32Array(0), 16000, new NullKeywordRecognizer());
  assert.equal(d.route, "silent_wait");
});

test("hinglish greeting matches via language + english fallback keywords", () => {
  const router = makeRouter();
  const d = router.classifyText("hello boliye", { language: "hinglish" });
  assert.equal(d.route, "cached_filler");
  assert.equal(d.intent, "greeting");
});
