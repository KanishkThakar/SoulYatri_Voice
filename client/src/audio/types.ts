/**
 * SoulYatri Client — Shared audio types (Phase 2A/2B/2C)
 *
 * These TypeScript types mirror the wire contract in `shared/contracts.py`
 * (`AudioFrame`) and `docs/INTERFACES.md` §1.1. The in-process client view uses
 * a `Float32Array` of mono samples in [-1, 1]; the on-the-wire form is raw PCM16
 * bytes produced by {@link frameToPcm16}.
 */

/**
 * A single chunk of captured PCM audio.
 *
 * Matches the `final_use.md` §2 skeleton `{ pcm, tsMs }` and the shared
 * `AudioFrame` contract (with optional correlation fields used by transport).
 */
export interface AudioFrame {
  /** Float32 mono samples in [-1, 1]. */
  pcm: Float32Array;
  /** Capture/emit timestamp in milliseconds (epoch ms). */
  tsMs: number;
  /** Monotonic frame index within the session (set by capture/transport). */
  seq?: number;
  /** Owning session id (attached by transport). */
  sessionId?: string;
  /** Sample rate the `pcm` was captured at (Hz). */
  sampleRate?: number;
  /** Marks the final frame of a stream/turn. */
  isFinal?: boolean;
}

/** Serializable form of an {@link AudioFrame} matching `shared.contracts.AudioFrame`. */
export interface AudioFrameWire {
  session_id: string;
  seq: number;
  pcm: number[];
  sample_rate: number;
  ts_ms: number;
  is_final: boolean;
}

/** Convert an in-process frame to the JSON-wire contract shape. */
export function frameToWire(
  frame: AudioFrame,
  fallback: { sessionId: string; seq: number; sampleRate: number }
): AudioFrameWire {
  return {
    session_id: frame.sessionId ?? fallback.sessionId,
    seq: frame.seq ?? fallback.seq,
    pcm: Array.from(frame.pcm),
    sample_rate: frame.sampleRate ?? fallback.sampleRate,
    ts_ms: frame.tsMs,
    is_final: frame.isFinal ?? false,
  };
}

/** Convert float32 samples [-1, 1] to little-endian PCM16 bytes for transport. */
export function frameToPcm16(frame: AudioFrame): ArrayBuffer {
  const { pcm } = frame;
  const out = new Int16Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}

/** Convert little-endian PCM16 bytes back into float32 samples in [-1, 1]. */
export function pcm16ToFloat32(buffer: ArrayBuffer): Float32Array {
  const int16 = new Int16Array(buffer);
  const out = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    out[i] = int16[i] / 32768.0;
  }
  return out;
}

/**
 * Linear-resample float32 PCM from `fromRate` to `toRate`.
 * Lightweight (linear interpolation) — adequate for capture rate alignment.
 */
export function resampleLinear(
  input: Float32Array,
  fromRate: number,
  toRate: number
): Float32Array {
  if (fromRate === toRate || input.length === 0) return input;
  const ratio = toRate / fromRate;
  const outLength = Math.max(1, Math.round(input.length * ratio));
  const out = new Float32Array(outLength);
  for (let i = 0; i < outLength; i++) {
    const srcPos = i / ratio;
    const lo = Math.floor(srcPos);
    const hi = Math.min(lo + 1, input.length - 1);
    const frac = srcPos - lo;
    out[i] = input[lo] * (1 - frac) + input[hi] * frac;
  }
  return out;
}
