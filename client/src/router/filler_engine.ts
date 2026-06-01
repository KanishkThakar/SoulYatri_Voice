/**
 * SoulYatri Client — Filler Playback Engine (Phase 3C)
 * =====================================================
 * Bounded, safe, cancellable filler playback policy. Plays a cached phrase to
 * mask latency while the full speech-native stack works, then hands off cleanly
 * to the main output. It must never override a complex turn's real answer.
 *
 * Acceptance (final_use.md §Phase-3C): filler triggers are deterministic,
 * cancellable, and do not override complex turns.
 *
 * Policy summary (final_use.md §2.3 frozen filler rule — simple, safe, bounded)
 * ----------------------------------------------------------------------------
 * * **Immediate filler** — for trivial turns (`cached_filler` route), play the
 *   phrase right away; this *is* the answer, no handoff to main output.
 * * **Latency-sponge filler** — for complex turns flagged
 *   `emitFillerThenForward`, play a short stall phrase to buy 300–700 ms, but
 *   always hand off to the main output when it arrives. The filler is faded out;
 *   the real answer is never suppressed.
 * * **Disable switch** — `enabled=false` makes the engine a no-op (returns a
 *   `skipped` plan), so the latency layer can be turned off entirely.
 * * **Safe classes only** — only phrases tagged `safe` are ever played.
 * * **Cancellable** — `cancel()` aborts an in-flight filler (barge-in / main
 *   output ready) via fadeout or hard-cut.
 */

import { StreamPlayer } from "../playback/stream_player";
import { PhraseBank, PhraseRecord } from "./phrase_schema";
import { RouteDecision } from "./intent_router";

export interface FillerLogger {
  info(event: string, data?: Record<string, unknown>): void;
  warn(event: string, data?: Record<string, unknown>): void;
}

const defaultLogger: FillerLogger = {
  info: (event, data) => console.info(`[filler] ${event}`, data ?? {}),
  warn: (event, data) => console.warn(`[filler] ${event}`, data ?? {}),
};

/** Loads audio bytes for a phrase (e.g. fetch from public/audio). */
export type AudioLoader = (phrase: PhraseRecord) => Promise<ArrayBuffer | Float32Array>;

export type FillerAction =
  | "immediate" // trivial turn; filler is the answer
  | "latency_sponge" // complex turn; filler buys time, then hand off
  | "skipped"; // disabled, unsafe, or no phrase

export interface FillerPlan {
  action: FillerAction;
  phraseId: string | null;
  /** Whether the engine still expects the main output to take over. */
  expectsHandoff: boolean;
  reason: string;
}

export interface FillerEngineConfig {
  player: StreamPlayer;
  phraseBank: PhraseBank;
  /** Loads the phrase audio. Required to actually play. */
  audioLoader?: AudioLoader;
  /** Master enable switch. Default true. */
  enabled?: boolean;
  /** Sample rate of filler audio assets (Hz). Default 24000. */
  fillerSampleRate?: number;
  /** Max filler duration to allow (ms). Bounds the latency sponge. Default 1500. */
  maxFillerMs?: number;
  logger?: FillerLogger;
}

/** Result of a play attempt; useful for callers/tests. */
export interface FillerPlayResult {
  plan: FillerPlan;
  played: boolean;
}

/**
 * The filler engine. One instance per session. Holds at most one active filler;
 * a new turn or a handoff cancels the previous one.
 */
export class FillerEngine {
  private readonly player: StreamPlayer;
  private readonly bank: PhraseBank;
  private readonly audioLoader?: AudioLoader;
  private readonly fillerSampleRate: number;
  private readonly maxFillerMs: number;
  private readonly logger: FillerLogger;

  private _enabled: boolean;
  private activePhraseId: string | null = null;
  private activeIsSponge = false;
  private handedOff = false;
  private generation = 0; // bumped on cancel/new turn to invalidate in-flight loads

  constructor(config: FillerEngineConfig) {
    this.player = config.player;
    this.bank = config.phraseBank;
    this.audioLoader = config.audioLoader;
    this.fillerSampleRate = config.fillerSampleRate ?? 24000;
    this.maxFillerMs = config.maxFillerMs ?? 1500;
    this.logger = config.logger ?? defaultLogger;
    this._enabled = config.enabled ?? true;
  }

  get enabled(): boolean {
    return this._enabled;
  }

  /** Disable switch (final_use.md §2.3): turn the latency layer on/off. */
  setEnabled(enabled: boolean): void {
    this._enabled = enabled;
    this.logger.info("filler_enabled_changed", { enabled });
    if (!enabled) this.cancel("hard");
  }

  get activeFillerId(): string | null {
    return this.activePhraseId;
  }

  /**
   * Decide the filler plan for a route decision **without** playing. Deterministic
   * and side-effect free, so it is easy to unit test.
   */
  plan(decision: RouteDecision): FillerPlan {
    if (!this._enabled) {
      return { action: "skipped", phraseId: null, expectsHandoff: false, reason: "disabled" };
    }
    if (!decision.phraseId) {
      return {
        action: "skipped",
        phraseId: null,
        expectsHandoff: decision.route === "full_stack",
        reason: "no phrase id on decision",
      };
    }

    const phrase = this.bank.get(decision.phraseId);
    if (!phrase) {
      return {
        action: "skipped",
        phraseId: null,
        expectsHandoff: decision.route === "full_stack",
        reason: `unknown phrase ${decision.phraseId}`,
      };
    }
    // Safety gate: only auto-play 'safe' phrases.
    if (phrase.safetyTag !== "safe") {
      this.logger.warn("filler_blocked_unsafe", { phraseId: phrase.id, tag: phrase.safetyTag });
      return {
        action: "skipped",
        phraseId: null,
        expectsHandoff: decision.route === "full_stack",
        reason: `phrase ${phrase.id} not safe (${phrase.safetyTag})`,
      };
    }
    // Bound the filler length (latency layer must stay short).
    if (phrase.duration * 1000 > this.maxFillerMs) {
      this.logger.warn("filler_too_long", { phraseId: phrase.id, durationMs: phrase.duration * 1000 });
      return {
        action: "skipped",
        phraseId: null,
        expectsHandoff: decision.route === "full_stack",
        reason: `phrase ${phrase.id} exceeds maxFillerMs`,
      };
    }

    if (decision.route === "cached_filler" && !decision.emitFillerThenForward) {
      // Trivial turn — filler is the whole answer.
      return { action: "immediate", phraseId: phrase.id, expectsHandoff: false, reason: "trivial cached turn" };
    }

    // Complex turn — filler is a latency sponge; main output must take over.
    return {
      action: "latency_sponge",
      phraseId: phrase.id,
      expectsHandoff: true,
      reason: "latency sponge; awaiting main output",
    };
  }

  /**
   * Plan and play the filler for a decision. Returns whether audio was played.
   * Cancels any previously-active filler first (one filler at a time).
   */
  async play(decision: RouteDecision): Promise<FillerPlayResult> {
    const plan = this.plan(decision);
    if (plan.action === "skipped" || !plan.phraseId) {
      this.logger.info("filler_skip", { reason: plan.reason });
      return { plan, played: false };
    }

    // New filler invalidates any in-flight one.
    this.cancel("hard");
    const myGeneration = ++this.generation;

    const phrase = this.bank.get(plan.phraseId)!;
    this.activePhraseId = phrase.id;
    this.activeIsSponge = plan.action === "latency_sponge";
    this.handedOff = false;

    if (!this.audioLoader) {
      this.logger.warn("filler_no_audio_loader", { phraseId: phrase.id });
      return { plan, played: false };
    }

    let audio: ArrayBuffer | Float32Array;
    try {
      audio = await this.audioLoader(phrase);
    } catch (err) {
      this.logger.warn("filler_audio_load_failed", { phraseId: phrase.id, error: String(err) });
      this.activePhraseId = null;
      return { plan, played: false };
    }

    // A cancel/new turn may have happened while loading — don't play stale audio.
    if (myGeneration !== this.generation) {
      this.logger.info("filler_load_superseded", { phraseId: phrase.id });
      return { plan, played: false };
    }

    this.player.beginTurn();
    if (audio instanceof Float32Array) {
      this.player.enqueue({ pcm: audio, sampleRate: this.fillerSampleRate, isFinal: true });
    } else {
      this.player.enqueuePcm16(audio, this.fillerSampleRate, undefined, true);
    }
    this.logger.info("filler_played", {
      phraseId: phrase.id,
      action: plan.action,
      durationMs: phrase.duration * 1000,
    });
    return { plan, played: true };
  }

  /**
   * Hand off to the main speech-native output. Fades out an active latency-sponge
   * filler so the real answer is never talked over. Returns true if a filler was
   * actively faded (i.e. a handoff happened).
   *
   * This is the guarantee that filler does **not** override complex turns.
   */
  async handoffToMain(): Promise<boolean> {
    if (!this.activePhraseId) return false;
    if (!this.activeIsSponge) {
      // Immediate (trivial) fillers are the answer; nothing to hand off.
      this.logger.info("filler_handoff_noop_trivial", { phraseId: this.activePhraseId });
      return false;
    }
    this.logger.info("filler_handoff", { phraseId: this.activePhraseId });
    this.handedOff = true;
    await this.player.fadeOut();
    this.activePhraseId = null;
    this.activeIsSponge = false;
    this.generation++; // invalidate any pending load
    return true;
  }

  /** Cancel any active filler immediately (barge-in) or with a fade. */
  cancel(mode: "fade" | "hard" = "hard"): void {
    this.generation++; // invalidate in-flight loads
    if (!this.activePhraseId) {
      if (mode === "hard") this.player.hardStop();
      return;
    }
    this.logger.info("filler_cancel", { phraseId: this.activePhraseId, mode });
    if (mode === "fade") {
      void this.player.fadeOut();
    } else {
      this.player.hardStop();
    }
    this.activePhraseId = null;
    this.activeIsSponge = false;
  }

  /** Whether a handoff to main output has occurred for the active turn. */
  get didHandoff(): boolean {
    return this.handedOff;
  }
}
