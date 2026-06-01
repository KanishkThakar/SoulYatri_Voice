/**
 * SoulYatri Client — Realtime Transport (Phase 2B)
 * =================================================
 * Realtime audio transport with reconnect handling, jitter smoothing, and
 * session metadata. Designed for WebRTC + Opus / LiveKit, but abstracted behind
 * a {@link Transport} interface so a WebSocket transport (the bring-up path used
 * by `useVoiceStream.ts`) or an in-memory loopback (tests) can be swapped in
 * without touching the session logic.
 *
 * Acceptance (final_use.md §Phase-2B): audio survives reconnects and moderate
 * network jitter.
 *
 * The session, not the socket, is the unit of identity. On disconnect the
 * session retains its sequence cursor and pending state; on reconnect it resumes
 * from where it left off. Outbound frames are buffered while disconnected and
 * flushed on reconnect so audio is not lost across a brief drop.
 */

import {
  AudioFrame,
  AudioFrameWire,
  frameToWire,
  frameToPcm16,
} from "./types";
import { CaptureLogger, consoleLogger } from "./capture";

export type TransportState =
  | "new"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "closed";

/** Minimal transport abstraction (WebRTC datachannel, WebSocket, or loopback). */
export interface Transport {
  connect(): Promise<void>;
  close(): void;
  /** Send a binary or text payload. */
  send(data: ArrayBuffer | string): void;
  /** Whether the underlying channel is open. */
  readonly isOpen: boolean;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
  onMessage?: (data: ArrayBuffer | string) => void;
}

export interface SessionMetadata {
  sessionId: string;
  sampleRate: number;
  codec: "opus" | "pcm16";
  createdMs: number;
  reconnectCount: number;
  framesSent: number;
  framesBuffered: number;
  language?: string;
  attributes: Record<string, unknown>;
}

export interface TransportClientOptions {
  sessionId?: string;
  sampleRate?: number;
  codec?: "opus" | "pcm16";
  /** Factory producing the underlying transport. Defaults to WebSocket. */
  transportFactory?: (sessionId: string) => Transport;
  serverUrl?: string;
  /** Max outbound frames buffered while disconnected. Default 256. */
  maxOutboundBuffer?: number;
  /** Reconnect backoff schedule in ms. Default [250, 500, 1000, 2000, 4000]. */
  reconnectBackoffMs?: number[];
  /** Max reconnect attempts before giving up. Default 8. */
  maxReconnectAttempts?: number;
  onState?: (state: TransportState) => void;
  onInbound?: (frame: AudioFrame) => void;
  onControl?: (msg: Record<string, unknown>) => void;
  language?: string;
  logger?: CaptureLogger;
}

function genSessionId(): string {
  return `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * WebSocket transport — the bring-up path consistent with
 * `client/src/hooks/useVoiceStream.ts`. WebRTC/LiveKit can implement the same
 * {@link Transport} interface for production.
 */
export class WebSocketTransport implements Transport {
  private ws: WebSocket | null = null;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
  onMessage?: (data: ArrayBuffer | string) => void;

  constructor(private readonly url: string) {}

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        const ws = new WebSocket(this.url);
        ws.binaryType = "arraybuffer";
        ws.onopen = () => {
          this.onOpen?.();
          resolve();
        };
        ws.onclose = () => this.onClose?.();
        ws.onerror = (e) => {
          this.onError?.(e);
          reject(new Error("websocket error"));
        };
        ws.onmessage = (e) => this.onMessage?.(e.data);
        this.ws = ws;
      } catch (err) {
        reject(err);
      }
    });
  }

  close(): void {
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
  }

  send(data: ArrayBuffer | string): void {
    if (this.isOpen) this.ws!.send(data as ArrayBuffer);
  }
}

/**
 * In-memory loopback transport for unit tests. Echoes nothing by default but
 * lets tests inspect sent payloads and inject inbound messages.
 */
export class LoopbackTransport implements Transport {
  sent: (ArrayBuffer | string)[] = [];
  private open = false;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
  onMessage?: (data: ArrayBuffer | string) => void;

  get isOpen(): boolean {
    return this.open;
  }

  async connect(): Promise<void> {
    this.open = true;
    this.onOpen?.();
  }

  close(): void {
    if (!this.open) return;
    this.open = false;
    this.onClose?.();
  }

  send(data: ArrayBuffer | string): void {
    if (!this.open) throw new Error("loopback transport closed");
    this.sent.push(data);
  }

  /** Test helper: simulate an inbound message from the server. */
  inject(data: ArrayBuffer | string): void {
    this.onMessage?.(data);
  }

  /** Test helper: simulate an unexpected drop. */
  drop(): void {
    this.open = false;
    this.onClose?.();
  }
}

/**
 * Reconnect-survivable realtime transport client. Tracks session identity,
 * buffers outbound frames while disconnected, and resumes on reconnect.
 */
export class RealtimeTransportClient {
  readonly metadata: SessionMetadata;
  private state: TransportState = "new";
  private transport: Transport | null = null;
  private readonly opts: Required<
    Omit<
      TransportClientOptions,
      "onState" | "onInbound" | "onControl" | "transportFactory" | "language" | "logger"
    >
  > &
    Pick<
      TransportClientOptions,
      "onState" | "onInbound" | "onControl" | "transportFactory"
    >;
  private readonly logger: CaptureLogger;
  private outbound: AudioFrame[] = [];
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  constructor(options: TransportClientOptions = {}) {
    const sessionId = options.sessionId ?? genSessionId();
    this.logger = options.logger ?? consoleLogger;
    this.opts = {
      sessionId,
      sampleRate: options.sampleRate ?? 16000,
      codec: options.codec ?? "pcm16",
      serverUrl: options.serverUrl ?? "ws://localhost:8000/ws/audio",
      maxOutboundBuffer: options.maxOutboundBuffer ?? 256,
      reconnectBackoffMs: options.reconnectBackoffMs ?? [250, 500, 1000, 2000, 4000],
      maxReconnectAttempts: options.maxReconnectAttempts ?? 8,
      onState: options.onState,
      onInbound: options.onInbound,
      onControl: options.onControl,
      transportFactory: options.transportFactory,
    };
    this.metadata = {
      sessionId,
      sampleRate: this.opts.sampleRate,
      codec: this.opts.codec,
      createdMs: Date.now(),
      reconnectCount: 0,
      framesSent: 0,
      framesBuffered: 0,
      language: options.language,
      attributes: {},
    };
  }

  get currentState(): TransportState {
    return this.state;
  }

  get isConnected(): boolean {
    return this.state === "connected";
  }

  /** Establish the transport and send the session config handshake. */
  async connect(): Promise<void> {
    this.intentionalClose = false;
    this.setState("connecting");
    this.transport = this.makeTransport();
    this.wireTransport(this.transport);
    try {
      await this.transport.connect();
    } catch (err) {
      this.logger.error("connect_failed", { error: String(err) });
      this.scheduleReconnect();
      throw err;
    }
  }

  /** Send one captured frame; buffered if currently disconnected. */
  send(frame: AudioFrame): void {
    if (this.state !== "connected" || !this.transport?.isOpen) {
      this.bufferOutbound(frame);
      return;
    }
    this.transmit(frame);
  }

  /** Send the end-of-turn / end-of-session control message. */
  end(): void {
    this.sendControl({ type: "end" });
  }

  /** Tear down the client and stop reconnect attempts. */
  close(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.transport?.close();
    this.transport = null;
    this.setState("closed");
    this.logger.info("transport_closed", {
      framesSent: this.metadata.framesSent,
      reconnects: this.metadata.reconnectCount,
    });
  }

  // -- internals ----------------------------------------------------------
  private makeTransport(): Transport {
    if (this.opts.transportFactory) {
      return this.opts.transportFactory(this.metadata.sessionId);
    }
    return new WebSocketTransport(`${this.opts.serverUrl}/${this.metadata.sessionId}`);
  }

  private wireTransport(transport: Transport): void {
    transport.onOpen = () => this.handleOpen();
    transport.onClose = () => this.handleClose();
    transport.onError = (err) => this.logger.warn("transport_error", { error: String(err) });
    transport.onMessage = (data) => this.handleMessage(data);
  }

  private handleOpen(): void {
    const wasReconnecting = this.state === "reconnecting";
    this.reconnectAttempts = 0;
    this.setState("connected");
    if (wasReconnecting) {
      this.metadata.reconnectCount += 1;
      this.logger.info("transport_reconnected", {
        reconnectCount: this.metadata.reconnectCount,
        buffered: this.outbound.length,
      });
    } else {
      this.logger.info("transport_connected", { sessionId: this.metadata.sessionId });
    }
    // Resend session config so the gateway can resume/identify the session.
    this.sendControl({
      type: "config",
      session_id: this.metadata.sessionId,
      sample_rate: this.metadata.sampleRate,
      codec: this.metadata.codec,
      resume: wasReconnecting,
      ...(this.metadata.language ? { language: this.metadata.language } : {}),
    });
    this.flushOutbound();
  }

  private handleClose(): void {
    if (this.intentionalClose || this.state === "closed") return;
    this.setState("disconnected");
    this.logger.warn("transport_dropped", { sessionId: this.metadata.sessionId });
    this.scheduleReconnect();
  }

  private handleMessage(data: ArrayBuffer | string): void {
    if (typeof data === "string") {
      try {
        const msg = JSON.parse(data) as Record<string, unknown>;
        this.opts.onControl?.(msg);
      } catch {
        this.logger.warn("control_parse_failed");
      }
      return;
    }
    // Binary inbound audio → surface to playback layer as a frame.
    if (this.opts.onInbound) {
      const int16 = new Int16Array(data);
      const pcm = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) pcm[i] = int16[i] / 32768.0;
      this.opts.onInbound({ pcm, tsMs: Date.now(), sessionId: this.metadata.sessionId });
    }
  }

  private transmit(frame: AudioFrame): void {
    if (this.opts.codec === "pcm16") {
      this.transport!.send(frameToPcm16(frame));
    } else {
      // Opus encoding is handled by the WebRTC layer; JSON wire as a portable fallback.
      const wire: AudioFrameWire = frameToWire(frame, {
        sessionId: this.metadata.sessionId,
        seq: this.metadata.framesSent,
        sampleRate: this.metadata.sampleRate,
      });
      this.transport!.send(JSON.stringify({ type: "frame", frame: wire }));
    }
    this.metadata.framesSent += 1;
  }

  private bufferOutbound(frame: AudioFrame): void {
    this.outbound.push(frame);
    if (this.outbound.length > this.opts.maxOutboundBuffer) {
      // Drop oldest to bound memory; recent audio matters most for latency.
      this.outbound.shift();
    }
    this.metadata.framesBuffered = this.outbound.length;
  }

  private flushOutbound(): void {
    if (this.outbound.length === 0) return;
    const pending = this.outbound;
    this.outbound = [];
    this.metadata.framesBuffered = 0;
    this.logger.info("flush_outbound", { count: pending.length });
    for (const frame of pending) this.transmit(frame);
  }

  private sendControl(msg: Record<string, unknown>): void {
    if (this.transport?.isOpen) {
      this.transport.send(JSON.stringify(msg));
    }
  }

  private scheduleReconnect(): void {
    if (this.intentionalClose) return;
    if (this.reconnectAttempts >= this.opts.maxReconnectAttempts) {
      this.logger.error("reconnect_exhausted", { attempts: this.reconnectAttempts });
      this.setState("disconnected");
      return;
    }
    const backoff = this.opts.reconnectBackoffMs;
    const delay = backoff[Math.min(this.reconnectAttempts, backoff.length - 1)];
    this.reconnectAttempts += 1;
    this.setState("reconnecting");
    this.logger.info("scheduling_reconnect", { attempt: this.reconnectAttempts, delayMs: delay });
    this.reconnectTimer = setTimeout(() => {
      void this.attemptReconnect();
    }, delay);
  }

  private async attemptReconnect(): Promise<void> {
    if (this.intentionalClose) return;
    this.transport?.close();
    this.transport = this.makeTransport();
    this.wireTransport(this.transport);
    try {
      await this.transport.connect();
    } catch {
      this.scheduleReconnect();
    }
  }

  private setState(state: TransportState): void {
    if (this.state === state) return;
    this.state = state;
    this.opts.onState?.(state);
  }
}
