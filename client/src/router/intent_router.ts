/**
 * SoulYatri Client — Local Intent Router (Phase 3B)
 * ==================================================
 * A tiny, local route classifier. It decides whether a turn can be answered
 * from the cached phrase bank, must escalate to the full speech-native stack, or
 * should wait silently. The output is shaped like `shared.contracts.RouteDecision`
 * (see `docs/INTERFACES.md` §4.1).
 *
 * Acceptance (final_use.md §Phase-3B): greetings/acknowledgements route to cached
 * paths with low false positives.
 *
 * Design
 * ------
 * * The classifier is pluggable via the {@link SpeechRecognizer} interface. A
 *   real deployment plugs in sherpa-onnx (tiny ASR / keyword spotting). When no
 *   recognizer is available we use a **deterministic keyword fallback** so the
 *   router always works on a CPU-only client with no model assets.
 * * Confidence thresholds gate cached routing; anything ambiguous escalates to
 *   the full stack. This keeps false positives low (per the acceptance test).
 * * Routing is deterministic given the same input + phrase bank, which makes it
 *   unit-testable.
 */

import { PhraseBank, PhraseCategory, PhraseLanguage } from "./phrase_schema";

/** Mirror of `shared.contracts.RouteTarget`. */
export type RouteTarget = "cached_filler" | "full_stack" | "silent_wait";

/** Mirror of `shared.contracts.RouteDecision` (client-side, camelCase). */
export interface RouteDecision {
  route: RouteTarget;
  phraseId: string | null;
  intent: string;
  confidence: number;
  reason: string;
  /** Latency sponge: play a filler AND forward to the full stack. */
  emitFillerThenForward: boolean;
}

/** Serializable form matching the Python `RouteDecision` JSON contract. */
export interface RouteDecisionWire {
  route: RouteTarget;
  phrase_id: string | null;
  intent: string;
  confidence: number;
  reason: string;
  emit_filler_then_forward: boolean;
}

export function toWire(d: RouteDecision): RouteDecisionWire {
  return {
    route: d.route,
    phrase_id: d.phraseId,
    intent: d.intent,
    confidence: d.confidence,
    reason: d.reason,
    emit_filler_then_forward: d.emitFillerThenForward,
  };
}

/** Result of recognizing/transcribing a short utterance. */
export interface RecognitionResult {
  transcript: string;
  /** Recognizer confidence in [0, 1]. */
  confidence: number;
  language?: PhraseLanguage;
}

/**
 * Pluggable recognizer. Implemented by a sherpa-onnx tiny ASR/KWS adapter in
 * production; the router ships with a keyword fallback when this is absent.
 */
export interface SpeechRecognizer {
  recognize(audio: Float32Array, sampleRate: number): Promise<RecognitionResult>;
}

/** Map of intent → per-language keyword lists (from phrase_bank.json). */
export type IntentKeywords = Record<string, Record<string, string[]>>;

export interface IntentRouterConfig {
  /** Phrase bank used to select a cached phrase for an intent. */
  phraseBank: PhraseBank;
  /** Keyword tables (typically `phrase_bank.json.intent_keywords`). */
  intentKeywords: IntentKeywords;
  /** Default language when none is detected. */
  defaultLanguage?: PhraseLanguage;
  /** Min confidence to route a trivial turn to a cached filler. Default 0.6. */
  cacheConfidenceThreshold?: number;
  /** Max word count for a turn to be considered "trivial". Default 5. */
  trivialMaxWords?: number;
  /** Optional logger. */
  logger?: { info(event: string, data?: Record<string, unknown>): void };
}

const DEFAULT_THRESHOLD = 0.6;
const DEFAULT_TRIVIAL_WORDS = 5;

/**
 * Local route classifier. Use {@link classifyText} for already-transcribed
 * input, or {@link classifyAudio} with a {@link SpeechRecognizer}.
 */
export class IntentRouter {
  private readonly bank: PhraseBank;
  private readonly keywords: IntentKeywords;
  private readonly defaultLanguage: PhraseLanguage;
  private readonly threshold: number;
  private readonly trivialMaxWords: number;
  private readonly logger?: IntentRouterConfig["logger"];

  constructor(config: IntentRouterConfig) {
    this.bank = config.phraseBank;
    this.keywords = config.intentKeywords;
    this.defaultLanguage = config.defaultLanguage ?? "hinglish";
    this.threshold = config.cacheConfidenceThreshold ?? DEFAULT_THRESHOLD;
    this.trivialMaxWords = config.trivialMaxWords ?? DEFAULT_TRIVIAL_WORDS;
    this.logger = config.logger;
  }

  /** Classify an already-transcribed utterance into a {@link RouteDecision}. */
  classifyText(
    text: string,
    opts: { language?: PhraseLanguage; asrConfidence?: number; emotion?: string } = {}
  ): RouteDecision {
    const language = opts.language ?? this.defaultLanguage;
    const asrConfidence = opts.asrConfidence ?? 1.0;
    const normalized = text.toLowerCase().trim();
    const words = normalized.split(/\s+/).filter(Boolean);
    const wordSet = new Set(words);
    const wordCount = words.length;

    // --- Empathy path: emotional distress → filler + full stack ---
    if (opts.emotion && ["sad", "angry", "fear", "distress"].includes(opts.emotion)) {
      const phrase = this.bank.pick({ category: "empathy", language });
      return this.decision({
        route: phrase ? "cached_filler" : "full_stack",
        phraseId: phrase?.id ?? null,
        intent: "emotional",
        confidence: Math.min(0.7, asrConfidence),
        reason: `emotion=${opts.emotion}`,
        emitFillerThenForward: true,
      });
    }

    // --- Trivial keyword intents (greeting/farewell/confirmation/ack) ---
    if (wordCount > 0 && wordCount <= this.trivialMaxWords) {
      const trivial = this.matchTrivialIntent(wordSet, language, wordCount, asrConfidence);
      if (trivial) return trivial;
    }

    // --- Default: complex turn → stall filler + forward to full stack ---
    const stall = this.bank.pick({ category: "stall", language });
    return this.decision({
      route: "full_stack",
      phraseId: stall?.id ?? null,
      intent: "complex",
      confidence: 0.0,
      reason: "no trivial keyword match; escalating to full stack",
      emitFillerThenForward: stall != null,
    });
  }

  /** Recognize audio then classify. Falls back to silent wait on empty input. */
  async classifyAudio(
    audio: Float32Array,
    sampleRate: number,
    recognizer: SpeechRecognizer,
    opts: { emotion?: string } = {}
  ): Promise<RouteDecision> {
    const result = await recognizer.recognize(audio, sampleRate);
    if (!result.transcript.trim()) {
      return this.decision({
        route: "silent_wait",
        phraseId: null,
        intent: "unknown",
        confidence: result.confidence,
        reason: "empty transcript",
        emitFillerThenForward: false,
      });
    }
    return this.classifyText(result.transcript, {
      language: result.language,
      asrConfidence: result.confidence,
      emotion: opts.emotion,
    });
  }

  // -- internals ----------------------------------------------------------
  private matchTrivialIntent(
    wordSet: Set<string>,
    language: PhraseLanguage,
    wordCount: number,
    asrConfidence: number
  ): RouteDecision | null {
    // Intent → (category, max words for that intent, base confidence).
    const specs: { intent: string; category: PhraseCategory; maxWords: number; base: number }[] = [
      { intent: "greeting", category: "greeting", maxWords: 5, base: 0.85 },
      { intent: "farewell", category: "farewell", maxWords: 5, base: 0.85 },
      { intent: "confirmation", category: "confirmation", maxWords: 3, base: 0.8 },
      { intent: "acknowledgment", category: "acknowledgment", maxWords: 2, base: 0.75 },
    ];

    for (const spec of specs) {
      if (wordCount > spec.maxWords) continue;
      const kw = this.keywordsFor(spec.intent, language);
      if (!this.hasOverlap(wordSet, kw)) continue;

      const confidence = spec.base * asrConfidence;
      if (confidence < this.threshold) {
        // Matched keyword but recognizer not confident enough → escalate.
        this.logger?.info("router_below_threshold", { intent: spec.intent, confidence });
        continue;
      }
      const phrase = this.bank.pick({
        category: spec.category,
        language,
        maxRequiredConfidence: confidence,
      });
      if (!phrase) continue;

      this.logger?.info("router_cached_route", { intent: spec.intent, phraseId: phrase.id });
      return this.decision({
        route: "cached_filler",
        phraseId: phrase.id,
        intent: spec.intent,
        confidence,
        reason: `${spec.intent} keyword match`,
        emitFillerThenForward: false,
      });
    }
    return null;
  }

  private keywordsFor(intent: string, language: PhraseLanguage): Set<string> {
    const table = this.keywords[intent] ?? {};
    const set = new Set<string>();
    for (const w of table[language] ?? []) set.add(w);
    for (const w of table["en"] ?? []) set.add(w); // English is the lingua franca fallback
    return set;
  }

  private hasOverlap(words: Set<string>, keywords: Set<string>): boolean {
    for (const w of words) if (keywords.has(w)) return true;
    return false;
  }

  private decision(d: RouteDecision): RouteDecision {
    return d;
  }
}

/**
 * Deterministic keyword-only recognizer used when sherpa-onnx is unavailable.
 * It does not actually transcribe audio; callers should prefer {@link classifyText}
 * with text from the bring-up STT path. This exists so {@link classifyAudio} has a
 * safe, dependency-free default.
 */
export class NullKeywordRecognizer implements SpeechRecognizer {
  async recognize(): Promise<RecognitionResult> {
    return { transcript: "", confidence: 0 };
  }
}

/**
 * Lazily load a sherpa-onnx recognizer if the optional dependency is installed.
 * Returns null when unavailable so the caller can fall back to keywords. The
 * dynamic import keeps the heavy dependency out of the default bundle.
 */
export async function tryLoadSherpaRecognizer(): Promise<SpeechRecognizer | null> {
  try {
    // The package name is resolved at runtime; absent in CPU-only/dev installs.
    const mod = (await import(
      /* webpackIgnore: true */ "sherpa-onnx" as string
    ).catch(() => null)) as unknown as { createRecognizer?: () => SpeechRecognizer } | null;
    if (mod?.createRecognizer) return mod.createRecognizer();
    return null;
  } catch {
    return null;
  }
}
