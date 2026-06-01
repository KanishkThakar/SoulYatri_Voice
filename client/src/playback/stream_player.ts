/**
 * SoulYatri Client — Streaming Playback (Phase 2C)
 * =================================================
 * Receives PCM / chunked audio, plays it immediately as it arrives, and stops
 * cleanly on interruption (fadeout or hard-cut). Designed for low buffering so
 * assistant audio begins quickly, and for clean cancellation on barge-in.
 *
 * Acceptance (final_use.md §Phase-2C): assistant audio begins quickly and stops
 * cleanly on cancel.
 *
 * Strategy
 * --------
 * * Each chunk is scheduled back-to-back on the {@link AudioContext} clock using
 *   a running `nextStartTime` cursor, which avoids gaps/overlaps without large
 *   buffers (gapless streaming).
 * * Interruption fades a master gain to zero over a short window (default 60 ms)
 *   then stops all sources — no clicks, no trailing audio.
 * * `hardStop()` cancels instantly for barge-in where every millisecond counts.
 * * A small reorder buffer accepts out-of-order `seq` chunks (inbound jitter).
 */

import { CaptureLogger, consoleLogger } from "../audio/capture";
import { pcm16ToFloat32 } from "../audio/types";

export interface PlaybackChunk {
  /** Float32 mono samples in [-1, 1]. */
  pcm: Float32Array;
  /** Sample rate of this chunk (Hz). */
  sampleRate: number;
  /** Optional ordering index for inbound jitter smoothing. */
  seq?: number;
  /** Marks the last chunk of a response/turn. */
  isFinal?: boolean;
}

export interface StreamPlayerOptions {
  /** Fadeout duration in ms for soft interruption. Default 60. */
  fadeOutMs?: number;
  /** Reorder window for out-of-order chunks. Default 8. */
  jitterWindow?: number;
  /** Called when playback starts (first audible chunk). */
  onStart?: () => void;
  /** Called when the queue drains and playback ends naturally. */
  onEnd?: () => void;
  /** Called when playback is interrupted. */
  onInterrupt?: (mode: "fade" | "hard") => void;
  logger?: CaptureLogger;
}

type ManagedSource = {
  node: AudioBufferSourceNode;
  endsAt: number;
};

export class StreamPlayer {
  private ctx: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  private nextStartTime = 0;
  private sources = new Set<ManagedSource>();
  private playing = false;
  private startedThisTurn = false;
  private readonly opts: Required<Omit<StreamPlayerOptions, "onStart" | "onEnd" | "onInterrupt" | "logger">> &
    Pick<StreamPlayerOptions, "onStart" | "onEnd" | "onInterrupt"> & { logger: CaptureLogger };

  // Inbound jitter reorder buffer.
  private pending = new Map<number, PlaybackChunk>();
  private expectedSeq = 0;

  constructor(options: StreamPlayerOptions = {}) {
    this.opts = {
      fadeOutMs: options.fadeOutMs ?? 60,
      jitterWindow: options.jitterWindow ?? 8,
      onStart: options.onStart,
      onEnd: options.onEnd,
      onInterrupt: options.onInterrupt,
      logger: options.logger ?? consoleLogger,
    };
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  /** Lazily create the audio context (must follow a user gesture in browsers). */
  private ensureContext(): AudioContext {
    if (!this.ctx) {
      const AudioCtx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new AudioCtx();
      this.masterGain = this.ctx.createGain();
      this.masterGain.gain.value = 1;
      this.masterGain.connect(this.ctx.destination);
      this.nextStartTime = this.ctx.currentTime;
      this.opts.logger.info("player_context_created", { sampleRate: this.ctx.sampleRate });
    }
    return this.ctx;
  }

  /**
   * Begin a fresh playback turn. Resets the master gain (in case a prior fade
   * left it at zero) and the jitter cursor.
   */
  beginTurn(): void {
    const ctx = this.ensureContext();
    if (this.masterGain) {
      this.masterGain.gain.cancelScheduledValues(ctx.currentTime);
      this.masterGain.gain.setValueAtTime(1, ctx.currentTime);
    }
    this.nextStartTime = ctx.currentTime;
    this.startedThisTurn = false;
    this.pending.clear();
    this.expectedSeq = 0;
    this.opts.logger.info("player_turn_begin");
  }

  /** Enqueue a raw PCM16 byte chunk (e.g. straight from the socket). */
  enqueuePcm16(buffer: ArrayBuffer, sampleRate: number, seq?: number, isFinal?: boolean): void {
    this.enqueue({ pcm: pcm16ToFloat32(buffer), sampleRate, seq, isFinal });
  }

  /** Enqueue a chunk for immediate playback (reordered if `seq` is provided). */
  enqueue(chunk: PlaybackChunk): void {
    if (chunk.seq === undefined) {
      this.scheduleChunk(chunk);
      return;
    }
    // Jitter smoothing: hold out-of-order chunks briefly, release in order.
    if (chunk.seq < this.expectedSeq) {
      this.opts.logger.warn("player_drop_stale_chunk", { seq: chunk.seq });
      return;
    }
    this.pending.set(chunk.seq, chunk);
    while (this.pending.has(this.expectedSeq)) {
      const next = this.pending.get(this.expectedSeq)!;
      this.pending.delete(this.expectedSeq);
      this.expectedSeq += 1;
      this.scheduleChunk(next);
    }
    // Overflow guard: if we wait too long for a missing seq, skip the gap.
    if (this.pending.size > this.opts.jitterWindow) {
      const lowest = Math.min(...this.pending.keys());
      this.opts.logger.warn("player_skip_gap", { from: this.expectedSeq, to: lowest });
      this.expectedSeq = lowest;
      while (this.pending.has(this.expectedSeq)) {
        const next = this.pending.get(this.expectedSeq)!;
        this.pending.delete(this.expectedSeq);
        this.expectedSeq += 1;
        this.scheduleChunk(next);
      }
    }
  }

  private scheduleChunk(chunk: PlaybackChunk): void {
    if (chunk.pcm.length === 0) {
      if (chunk.isFinal) this.markFinal();
      return;
    }
    const ctx = this.ensureContext();
    if (ctx.state === "suspended") void ctx.resume();

    const buffer = ctx.createBuffer(1, chunk.pcm.length, chunk.sampleRate);
    buffer.getChannelData(0).set(chunk.pcm);

    const node = ctx.createBufferSource();
    node.buffer = buffer;
    node.connect(this.masterGain!);

    // Schedule gaplessly: never start in the past.
    const startAt = Math.max(this.nextStartTime, ctx.currentTime);
    node.start(startAt);
    const endsAt = startAt + buffer.duration;
    this.nextStartTime = endsAt;

    const managed: ManagedSource = { node, endsAt };
    this.sources.add(managed);

    if (!this.startedThisTurn) {
      this.startedThisTurn = true;
      this.playing = true;
      this.opts.onStart?.();
      this.opts.logger.info("player_started", { startAt, sampleRate: chunk.sampleRate });
    }

    node.onended = () => {
      this.sources.delete(managed);
      if (this.sources.size === 0 && this.playing) {
        this.playing = false;
        this.opts.logger.info("player_drained");
        this.opts.onEnd?.();
      }
    };

    if (chunk.isFinal) this.markFinal();
  }

  private markFinal(): void {
    this.opts.logger.info("player_final_chunk_received");
  }

  /**
   * Soft interruption: fade the master gain to zero over `fadeOutMs`, then stop
   * all sources. Use for natural endings/handoffs (no click).
   */
  async fadeOut(): Promise<void> {
    if (!this.ctx || !this.masterGain || !this.playing) {
      this.hardStop();
      return;
    }
    const ctx = this.ctx;
    const now = ctx.currentTime;
    const fadeSec = this.opts.fadeOutMs / 1000;
    this.opts.logger.info("player_fadeout", { fadeMs: this.opts.fadeOutMs });
    this.opts.onInterrupt?.("fade");

    this.masterGain.gain.cancelScheduledValues(now);
    this.masterGain.gain.setValueAtTime(this.masterGain.gain.value, now);
    this.masterGain.gain.linearRampToValueAtTime(0.0001, now + fadeSec);

    await new Promise((resolve) => setTimeout(resolve, this.opts.fadeOutMs));
    this.stopAllSources();
  }

  /**
   * Hard interruption (barge-in): stop every source immediately. Fastest possible
   * cancel; may click but guarantees the assistant goes silent at once.
   */
  hardStop(): void {
    if (!this.playing && this.sources.size === 0) return;
    this.opts.logger.info("player_hardstop", { sources: this.sources.size });
    this.opts.onInterrupt?.("hard");
    this.stopAllSources();
  }

  private stopAllSources(): void {
    for (const managed of this.sources) {
      try {
        managed.node.onended = null;
        managed.node.stop();
        managed.node.disconnect();
      } catch {
        /* already stopped */
      }
    }
    this.sources.clear();
    this.pending.clear();
    this.playing = false;
    if (this.ctx) this.nextStartTime = this.ctx.currentTime;
  }

  /** Release the audio context and all resources. */
  async dispose(): Promise<void> {
    this.stopAllSources();
    if (this.ctx) {
      await this.ctx.close();
      this.ctx = null;
      this.masterGain = null;
    }
    this.opts.logger.info("player_disposed");
  }
}
