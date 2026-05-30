/**
 * SoulYatri Client — Phrase-Bank Schema (Phase 3A)
 * =================================================
 * Metadata schema for cached filler phrases plus validation and search helpers.
 *
 * Acceptance (final_use.md §Phase-3A): phrase records validate and are
 * searchable.
 *
 * The schema mirrors the server-side `FillerPhrase` in `server/pipeline/filler.py`
 * (id, text, language, category, tone, intent, priority, min_confidence) and
 * extends it with the fields the guide calls for: `transcript`, `audioPath`,
 * `emotion`, `duration`, and a `safetyTag`. Keeping the field names aligned with
 * the server avoids a translation layer when phrase banks are shared.
 */

/** Closed set of safe filler categories (final_use.md §2.3: simple, safe, bounded). */
export const PHRASE_CATEGORIES = [
  "acknowledgment",
  "stall",
  "greeting",
  "confirmation",
  "empathy",
  "farewell",
] as const;
export type PhraseCategory = (typeof PHRASE_CATEGORIES)[number];

/** Supported languages (Hindi + English + Hinglish per the product identity). */
export const PHRASE_LANGUAGES = ["en", "hi", "hinglish"] as const;
export type PhraseLanguage = (typeof PHRASE_LANGUAGES)[number];

/**
 * Safety tag. Filler phrases must be safe by construction; only `safe` phrases
 * are eligible for autonomous playback. Anything else is held for review and is
 * never auto-played (final_use.md §2.4 safety rule).
 */
export const SAFETY_TAGS = ["safe", "needs_review", "blocked"] as const;
export type SafetyTag = (typeof SAFETY_TAGS)[number];

/** A single cached phrase record. */
export interface PhraseRecord {
  /** Stable unique id. */
  id: string;
  /** The display/spoken text. */
  text: string;
  /** Canonical transcript used for matching (lowercased form recommended). */
  transcript: string;
  /** Path to the pre-synthesized audio asset (relative to the audio root). */
  audioPath: string;
  /** Language of the phrase. */
  language: PhraseLanguage;
  /** Delivery tone (e.g. warm, neutral, calm). */
  tone: string;
  /** Intent this phrase answers (greeting, acknowledgment, complex-stall…). */
  intent: string;
  /** Coarse emotion label for delivery selection. */
  emotion: string;
  /** Category from {@link PHRASE_CATEGORIES}. */
  category: PhraseCategory;
  /** Audio duration in seconds (used for latency budgeting). */
  duration: number;
  /** Minimum router confidence required to use this phrase [0,1]. */
  confidence: number;
  /** Selection priority when multiple phrases match (higher wins). */
  priority: number;
  /** Safety classification; only `safe` is auto-playable. */
  safetyTag: SafetyTag;
}

export interface ValidationIssue {
  id: string;
  field: string;
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Validate a single phrase record. Returns the list of issues (empty if valid). */
export function validatePhrase(record: Partial<PhraseRecord>): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const id = record.id ?? "<missing-id>";
  const push = (field: string, message: string) => issues.push({ id, field, message });

  if (!record.id || typeof record.id !== "string") push("id", "id is required");
  if (!record.text || typeof record.text !== "string") push("text", "text is required");
  if (typeof record.transcript !== "string") push("transcript", "transcript is required");
  if (!record.audioPath || typeof record.audioPath !== "string")
    push("audioPath", "audioPath is required");

  if (!record.language || !PHRASE_LANGUAGES.includes(record.language as PhraseLanguage))
    push("language", `language must be one of ${PHRASE_LANGUAGES.join(", ")}`);
  if (!record.category || !PHRASE_CATEGORIES.includes(record.category as PhraseCategory))
    push("category", `category must be one of ${PHRASE_CATEGORIES.join(", ")}`);
  if (!record.safetyTag || !SAFETY_TAGS.includes(record.safetyTag as SafetyTag))
    push("safetyTag", `safetyTag must be one of ${SAFETY_TAGS.join(", ")}`);

  if (!isFiniteNumber(record.duration) || (record.duration as number) < 0)
    push("duration", "duration must be a non-negative number");
  if (!isFiniteNumber(record.confidence) || record.confidence! < 0 || record.confidence! > 1)
    push("confidence", "confidence must be within [0, 1]");
  if (!isFiniteNumber(record.priority)) push("priority", "priority must be a number");

  if (!record.tone || typeof record.tone !== "string") push("tone", "tone is required");
  if (!record.intent || typeof record.intent !== "string") push("intent", "intent is required");
  if (typeof record.emotion !== "string") push("emotion", "emotion is required");

  return issues;
}

/** Validate a list of phrase records and check id uniqueness. */
export function validatePhraseBank(records: Partial<PhraseRecord>[]): ValidationResult {
  const issues: ValidationIssue[] = [];
  const seen = new Set<string>();
  for (const record of records) {
    issues.push(...validatePhrase(record));
    if (record.id) {
      if (seen.has(record.id)) {
        issues.push({ id: record.id, field: "id", message: "duplicate id" });
      }
      seen.add(record.id);
    }
  }
  return { valid: issues.length === 0, issues };
}

export interface PhraseQuery {
  category?: PhraseCategory;
  language?: PhraseLanguage;
  intent?: string;
  tone?: string;
  emotion?: string;
  /** Free-text token to match against transcript/text. */
  text?: string;
  /** Only return auto-playable (`safe`) phrases. Default true. */
  safeOnly?: boolean;
  /** Minimum confidence the candidate phrase requires. */
  maxRequiredConfidence?: number;
}

/**
 * Searchable, validated in-memory phrase bank. Indexed by category and language
 * for fast lookup; falls back to scanning for text queries.
 */
export class PhraseBank {
  private readonly records: PhraseRecord[] = [];
  private readonly byId = new Map<string, PhraseRecord>();
  private readonly byCategory = new Map<PhraseCategory, PhraseRecord[]>();

  constructor(records: PhraseRecord[] = []) {
    for (const r of records) this.add(r);
  }

  /** Build a bank from raw JSON, throwing if any record is invalid. */
  static fromJSON(data: { phrases: Partial<PhraseRecord>[] }): PhraseBank {
    const result = validatePhraseBank(data.phrases);
    if (!result.valid) {
      throw new Error(
        `invalid phrase bank: ${result.issues
          .map((i) => `${i.id}.${i.field}: ${i.message}`)
          .join("; ")}`
      );
    }
    return new PhraseBank(data.phrases as PhraseRecord[]);
  }

  add(record: PhraseRecord): void {
    this.records.push(record);
    this.byId.set(record.id, record);
    const bucket = this.byCategory.get(record.category) ?? [];
    bucket.push(record);
    this.byCategory.set(record.category, bucket);
  }

  get size(): number {
    return this.records.length;
  }

  get(id: string): PhraseRecord | undefined {
    return this.byId.get(id);
  }

  all(): readonly PhraseRecord[] {
    return this.records;
  }

  /** Search the bank; results are sorted by priority (desc). */
  search(query: PhraseQuery): PhraseRecord[] {
    const safeOnly = query.safeOnly ?? true;
    let candidates = query.category
      ? this.byCategory.get(query.category) ?? []
      : this.records;

    const textToken = query.text?.toLowerCase().trim();

    candidates = candidates.filter((r) => {
      if (safeOnly && r.safetyTag !== "safe") return false;
      if (query.language && r.language !== query.language) return false;
      if (query.intent && r.intent !== query.intent) return false;
      if (query.tone && r.tone !== query.tone) return false;
      if (query.emotion && r.emotion !== query.emotion) return false;
      if (
        query.maxRequiredConfidence !== undefined &&
        r.confidence > query.maxRequiredConfidence
      )
        return false;
      if (textToken) {
        const hay = `${r.transcript} ${r.text}`.toLowerCase();
        if (!hay.includes(textToken)) return false;
      }
      return true;
    });

    return [...candidates].sort((a, b) => b.priority - a.priority);
  }

  /** Pick the best phrase for a query, or undefined if none match. */
  pick(query: PhraseQuery): PhraseRecord | undefined {
    return this.search(query)[0];
  }
}
