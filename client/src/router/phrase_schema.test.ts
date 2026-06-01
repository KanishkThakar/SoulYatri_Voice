/**
 * Unit tests for the phrase-bank schema (Phase 3A).
 *
 * Uses Node's built-in test runner (`node:test`). These modules contain no DOM
 * access, so they run headless. See client/src/README.md for how to run.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  PhraseBank,
  PhraseRecord,
  validatePhrase,
  validatePhraseBank,
} from "./phrase_schema";
import seed from "./phrase_bank.json";

const goodRecord: PhraseRecord = {
  id: "t1",
  text: "Got it.",
  transcript: "got it",
  audioPath: "fillers/t1.opus",
  language: "en",
  tone: "neutral",
  intent: "acknowledgment",
  emotion: "calm",
  category: "acknowledgment",
  duration: 0.5,
  confidence: 0.7,
  priority: 5,
  safetyTag: "safe",
};

test("validatePhrase accepts a well-formed record", () => {
  assert.deepEqual(validatePhrase(goodRecord), []);
});

test("validatePhrase flags missing/invalid fields", () => {
  const issues = validatePhrase({ id: "bad", confidence: 2, duration: -1 } as Partial<PhraseRecord>);
  const fields = issues.map((i) => i.field);
  assert.ok(fields.includes("text"));
  assert.ok(fields.includes("confidence"));
  assert.ok(fields.includes("duration"));
  assert.ok(fields.includes("language"));
});

test("validatePhraseBank detects duplicate ids", () => {
  const result = validatePhraseBank([goodRecord, { ...goodRecord }]);
  assert.equal(result.valid, false);
  assert.ok(result.issues.some((i) => i.message === "duplicate id"));
});

test("seed phrase_bank.json validates", () => {
  const result = validatePhraseBank(seed.phrases as Partial<PhraseRecord>[]);
  assert.equal(result.valid, true, JSON.stringify(result.issues));
});

test("PhraseBank.fromJSON builds and is searchable", () => {
  const bank = PhraseBank.fromJSON(seed as { phrases: Partial<PhraseRecord>[] });
  assert.ok(bank.size >= 10);

  const greetings = bank.search({ category: "greeting" });
  assert.ok(greetings.length >= 1);
  assert.ok(greetings.every((p) => p.category === "greeting"));

  // Sorted by priority desc.
  for (let i = 1; i < greetings.length; i++) {
    assert.ok(greetings[i - 1].priority >= greetings[i].priority);
  }

  // Language filter.
  const hi = bank.search({ category: "greeting", language: "hi" });
  assert.ok(hi.every((p) => p.language === "hi"));

  // Text search.
  const namaste = bank.search({ text: "namaste" });
  assert.ok(namaste.length >= 1);
});

test("search excludes unsafe phrases by default", () => {
  const bank = new PhraseBank([
    { ...goodRecord, id: "safe1", safetyTag: "safe" },
    { ...goodRecord, id: "review1", safetyTag: "needs_review" },
  ]);
  const safe = bank.search({});
  assert.ok(safe.every((p) => p.safetyTag === "safe"));
  const all = bank.search({ safeOnly: false });
  assert.equal(all.length, 2);
});
