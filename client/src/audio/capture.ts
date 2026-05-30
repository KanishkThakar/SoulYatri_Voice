/**
 * SoulYatri Client — Microphone Capture (Phase 2A)
 * =================================================
 * Captures mic PCM via `getUserMedia` + WebAudio, applies AEC + noise
 * suppression through `MediaTrackConstraints`, supports device selection and
 * permission handling, and emits {@link AudioFrame}s at a target sample rate.
 *
 * Acceptance (final_use.md §Phase-2A): user speech reaches the transport path
 * at the expected sample rate with no major clipping.
 *
 * Notes
 * -----
 * * AEC/NS/AGC are requested as track constraints (`echoCancellation`,
 *   `noiseSuppression`, `autoGainControl`). The browser's native DSP performs
 *   the heavy lifting; this keeps the client CPU-light.
 * * Capture happens in an `AudioWorklet` when available, falling back to the
 *   deprecated `ScriptProcessorNode` for older browsers.
 * * All meaningful events are logged through a pluggable logger for visibility.
 */

import {
  AudioFrame,
  resampleLinear,
} from "./types";

export interface CaptureLogger {
  info(event: string, data?: Record<string, unknown>): void;
  warn(event: string, data?: Record<string, unknown>): void;
  error(event: string, data?: Record<string, unknown>): void;
}

/** Default console-backed structured logger (visible logging, §3.3). */
export const consoleLogger: CaptureLogger = {
  info: (event, data) => console.info(`[capture] ${event}`, data ?? {}),
  warn: (event, data) => console.warn(`[capture] ${event}`, data ?? {}),
  error: (event, data) => console.error(`[capture] ${event}`, data ?? {}),
};

export interface CaptureOptions {
  /** Target sample rate handed to the transport (Hz). Default 16000. */
  targetSampleRate?: number;
  /** Frame size in samples emitted per {@link AudioFrame}. Default 1024. */
  frameSize?: number;
  /** Specific input device id (from {@link listInputDevices}). */
  deviceId?: string;
  /** Echo cancellation (AEC). Default true. */
  echoCancellation?: boolean;
  /** Noise suppression. Default true. */
  noiseSuppression?: boolean;
  /** Automatic gain control. Default true. */
  autoGainControl?: boolean;
  /** Callback invoked for each captured frame. */
  onFrame?: (frame: AudioFrame) => void;
  /** Callback invoked with a 0..1 input level for metering. */
  onLevel?: (level: number) => void;
  /** Callback invoked when clipping is detected (|sample| >= threshold). */
  onClip?: (ratio: number) => void;
  /** Structured logger. */
  logger?: CaptureLogger;
}

export type PermissionStatus = "granted" | "denied" | "prompt" | "unknown";

export interface InputDevice {
  deviceId: string;
  label: string;
}

const CLIP_THRESHOLD = 0.99;

/**
 * Query mic permission state without forcing a prompt where the Permissions API
 * is available. Returns "unknown" when the API is unsupported.
 */
export async function queryMicPermission(): Promise<PermissionStatus> {
  try {
    const perms = (navigator as Navigator & {
      permissions?: { query: (d: { name: PermissionName }) => Promise<{ state: string }> };
    }).permissions;
    if (!perms?.query) return "unknown";
    const result = await perms.query({ name: "microphone" as PermissionName });
    return (result.state as PermissionStatus) ?? "unknown";
  } catch {
    return "unknown";
  }
}

/** Enumerate available audio input devices (labels require a prior permission grant). */
export async function listInputDevices(): Promise<InputDevice[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices
    .filter((d) => d.kind === "audioinput")
    .map((d, i) => ({
      deviceId: d.deviceId,
      label: d.label || `Microphone ${i + 1}`,
    }));
}

/**
 * Microphone capture engine. Construct, then call {@link start}; {@link stop}
 * releases all resources. Re-usable across start/stop cycles.
 */
export class MicrophoneCapture {
  private readonly opts: Required<Omit<CaptureOptions, "deviceId" | "onFrame" | "onLevel" | "onClip" | "logger">> &
    Pick<CaptureOptions, "deviceId" | "onFrame" | "onLevel" | "onClip"> & { logger: CaptureLogger };

  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private scriptNode: ScriptProcessorNode | null = null;
  private analyser: AnalyserNode | null = null;
  private seq = 0;
  private running = false;
  private contextSampleRate = 48000;

  constructor(options: CaptureOptions = {}) {
    this.opts = {
      targetSampleRate: options.targetSampleRate ?? 16000,
      frameSize: options.frameSize ?? 1024,
      echoCancellation: options.echoCancellation ?? true,
      noiseSuppression: options.noiseSuppression ?? true,
      autoGainControl: options.autoGainControl ?? true,
      deviceId: options.deviceId,
      onFrame: options.onFrame,
      onLevel: options.onLevel,
      onClip: options.onClip,
      logger: options.logger ?? consoleLogger,
    };
  }

  get isRunning(): boolean {
    return this.running;
  }

  /** The sample rate at which frames are emitted. */
  get sampleRate(): number {
    return this.opts.targetSampleRate;
  }

  /**
   * Acquire the mic and begin emitting frames. Throws on permission denial or
   * when WebAudio is unavailable.
   */
  async start(): Promise<void> {
    if (this.running) {
      this.opts.logger.warn("start_ignored_already_running");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("getUserMedia is not available in this environment");
    }

    const constraints: MediaStreamConstraints = {
      audio: {
        channelCount: 1,
        echoCancellation: this.opts.echoCancellation,
        noiseSuppression: this.opts.noiseSuppression,
        autoGainControl: this.opts.autoGainControl,
        ...(this.opts.deviceId ? { deviceId: { exact: this.opts.deviceId } } : {}),
      },
    };

    this.opts.logger.info("requesting_microphone", {
      deviceId: this.opts.deviceId ?? "default",
      aec: this.opts.echoCancellation,
      ns: this.opts.noiseSuppression,
      agc: this.opts.autoGainControl,
    });

    try {
      this.stream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (err) {
      this.opts.logger.error("microphone_permission_error", { error: String(err) });
      throw err;
    }

    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.audioContext = new AudioCtx();
    this.contextSampleRate = this.audioContext.sampleRate;
    this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);

    // Analyser for level metering.
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.smoothingTimeConstant = 0.8;
    this.sourceNode.connect(this.analyser);

    await this.setupCaptureNode();

    this.running = true;
    this.seq = 0;
    this.opts.logger.info("capture_started", {
      contextSampleRate: this.contextSampleRate,
      targetSampleRate: this.opts.targetSampleRate,
      frameSize: this.opts.frameSize,
    });
  }

  /** Stop capture and release the mic, audio graph, and worklet. */
  async stop(): Promise<void> {
    this.running = false;

    if (this.workletNode) {
      this.workletNode.port.onmessage = null;
      this.workletNode.disconnect();
      this.workletNode = null;
    }
    if (this.scriptNode) {
      this.scriptNode.onaudioprocess = null;
      this.scriptNode.disconnect();
      this.scriptNode = null;
    }
    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.audioContext) {
      await this.audioContext.close();
      this.audioContext = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    this.opts.logger.info("capture_stopped", { framesEmitted: this.seq });
  }

  /** Read the current input level (0..1) from the analyser. */
  readLevel(): number {
    if (!this.analyser) return 0;
    const data = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i];
    return data.length ? sum / data.length / 255 : 0;
  }

  // -- internals ----------------------------------------------------------
  private async setupCaptureNode(): Promise<void> {
    const ctx = this.audioContext!;
    const supportsWorklet =
      typeof AudioWorkletNode !== "undefined" && !!ctx.audioWorklet;

    if (supportsWorklet) {
      try {
        await ctx.audioWorklet.addModule(captureWorkletUrl());
        this.workletNode = new AudioWorkletNode(ctx, "soulyatri-capture-processor", {
          numberOfInputs: 1,
          numberOfOutputs: 1,
          channelCount: 1,
          processorOptions: { frameSize: this.opts.frameSize },
        });
        this.workletNode.port.onmessage = (ev: MessageEvent) => {
          const samples = ev.data as Float32Array;
          this.handleSamples(samples);
        };
        this.sourceNode!.connect(this.workletNode);
        // Keep the graph pulling; a muted gain avoids feeding mic to speakers.
        const sink = ctx.createGain();
        sink.gain.value = 0;
        this.workletNode.connect(sink);
        sink.connect(ctx.destination);
        this.opts.logger.info("capture_node_worklet");
        return;
      } catch (err) {
        this.opts.logger.warn("worklet_failed_falling_back", { error: String(err) });
      }
    }

    // Fallback: ScriptProcessorNode (deprecated but broadly supported).
    const node = ctx.createScriptProcessor(this.opts.frameSize, 1, 1);
    node.onaudioprocess = (e: AudioProcessingEvent) => {
      if (!this.running) return;
      this.handleSamples(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    this.sourceNode!.connect(node);
    node.connect(ctx.destination);
    this.scriptNode = node;
    this.opts.logger.info("capture_node_scriptprocessor");
  }

  private handleSamples(samples: Float32Array): void {
    if (!this.running || samples.length === 0) return;

    // Clip detection (no major clipping is an acceptance criterion).
    let clipped = 0;
    let peak = 0;
    for (let i = 0; i < samples.length; i++) {
      const a = Math.abs(samples[i]);
      if (a > peak) peak = a;
      if (a >= CLIP_THRESHOLD) clipped++;
    }
    if (clipped > 0) {
      const ratio = clipped / samples.length;
      this.opts.onClip?.(ratio);
      this.opts.logger.warn("clipping_detected", { ratio, peak });
    }

    // Resample from the device/context rate to the target rate.
    const resampled = resampleLinear(
      samples,
      this.contextSampleRate,
      this.opts.targetSampleRate
    );

    const frame: AudioFrame = {
      pcm: resampled,
      tsMs: Date.now(),
      seq: this.seq++,
      sampleRate: this.opts.targetSampleRate,
      isFinal: false,
    };
    this.opts.onFrame?.(frame);
    this.opts.onLevel?.(peak);
  }
}

/**
 * Build a Blob URL for the capture AudioWorklet processor. Inlining the
 * processor avoids shipping a separate asset and keeps the module self-contained.
 */
function captureWorkletUrl(): string {
  const processorSource = `
    class SoulyatriCaptureProcessor extends AudioWorkletProcessor {
      constructor(options) {
        super();
        this.frameSize = (options.processorOptions && options.processorOptions.frameSize) || 1024;
        this._buf = new Float32Array(this.frameSize);
        this._filled = 0;
      }
      process(inputs) {
        const input = inputs[0];
        if (!input || input.length === 0) return true;
        const channel = input[0];
        if (!channel) return true;
        for (let i = 0; i < channel.length; i++) {
          this._buf[this._filled++] = channel[i];
          if (this._filled >= this.frameSize) {
            this.port.postMessage(this._buf.slice(0, this._filled));
            this._filled = 0;
          }
        }
        return true;
      }
    }
    registerProcessor('soulyatri-capture-processor', SoulyatriCaptureProcessor);
  `;
  const blob = new Blob([processorSource], { type: "application/javascript" });
  return URL.createObjectURL(blob);
}
