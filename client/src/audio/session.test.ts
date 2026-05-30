/**
 * Unit tests for the AudioSession orchestrator (Phase 2).
 *
 * The session is exercised with fake capture/transport/player collaborators so
 * no WebAudio/getUserMedia is needed. Verifies the guide skeleton contract
 * (start/stop/send), inbound→playback routing, barge-in, server-driven
 * interruption, and telemetry (send/receive jitter + buffer depth, §7.1).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { AudioFrame } from "./types";
import {
  SoulYatriAudioSession,
  CaptureLike,
  TransportLike,
  PlayerLike,
} from "./session";

class FakeCapture implements CaptureLike {
  isRunning = false;
  sampleRate = 16000;
  started = 0;
  stopped = 0;
  async start() {
    this.isRunning = true;
    this.started += 1;
  }
  async stop() {
    this.isRunning = false;
    this.stopped += 1;
  }
}

class FakeTransport implements TransportLike {
  isConnected = false;
  sent: AudioFrame[] = [];
  ended = 0;
  closed = 0;
  onInbound?: (f: AudioFrame) => void;
  onControl?: (m: Record<string, unknown>) => void;
  async connect() {
    this.isConnected = true;
  }
  close() {
    this.isConnected = false;
    this.closed += 1;
  }
  send(frame: AudioFrame) {
    this.sent.push(frame);
  }
  end() {
    this.ended += 1;
  }
  /** Test helper: simulate inbound assistant audio from the gateway. */
  injectInbound(frame: AudioFrame) {
    this.onInbound?.(frame);
  }
  /** Test helper: simulate a control message from the gateway. */
  injectControl(msg: Record<string, unknown>) {
    this.onControl?.(msg);
  }
}

class FakePlayer implements PlayerLike {
  calls: string[] = [];
  enqueued: { pcm: Float32Array; sampleRate: number }[] = [];
  beginTurn() {
    this.calls.push("beginTurn");
  }
  enqueue(chunk: { pcm: Float32Array; sampleRate: number }) {
    this.calls.push("enqueue");
    this.enqueued.push(chunk);
  }
  async fadeOut() {
    this.calls.push("fadeOut");
  }
  hardStop() {
    this.calls.push("hardStop");
  }
}

function makeSession(controlSink?: (m: Record<string, unknown>) => void) {
  const capture = new FakeCapture();
  const transport = new FakeTransport();
  const player = new FakePlayer();
  const session = new SoulYatriAudioSession({
    capture,
    transport,
    player,
    onControl: controlSink,
  });
  return { capture, transport, player, session };
}

function frame(pcm: number[], tsMs: number, extra: Partial<AudioFrame> = {}): AudioFrame {
  return { pcm: new Float32Array(pcm), tsMs, ...extra };
}

test("start connects transport and starts capture", async () => {
  const { capture, transport, session } = makeSession();
  await session.start();
  assert.equal(transport.isConnected, true);
  assert.equal(capture.started, 1);
  assert.equal(session.isRunning, true);
});

test("send forwards frames to the transport and counts them", () => {
  const { transport, session } = makeSession();
  session.send(frame([0.1, 0.2], 1000));
  session.send(frame([0.3], 1020));
  assert.equal(transport.sent.length, 2);
  assert.equal(session.telemetry().framesSent, 2);
});

test("inbound frames are enqueued for playback at the playback sample rate", () => {
  const { transport, player, session } = makeSession();
  transport.injectInbound(frame([0.1, 0.2], 1000));
  assert.ok(player.calls.includes("enqueue"));
  assert.equal(player.enqueued.length, 1);
  assert.equal(player.enqueued[0].sampleRate, 24000);
  assert.equal(session.telemetry().framesReceived, 1);
});

test("inbound frame honors its own sample rate when provided", () => {
  const { transport, player, session } = makeSession();
  transport.injectInbound(frame([0.1], 1000, { sampleRate: 16000 }));
  assert.equal(player.enqueued[0].sampleRate, 16000);
  assert.equal(session.telemetry().framesReceived, 1);
});

test("server-driven interrupt control triggers a barge-in stop", () => {
  const seen: Record<string, unknown>[] = [];
  const { transport, player } = makeSession((m) => seen.push(m));
  // Make the player think it is playing by enqueuing a chunk first.
  transport.injectInbound(frame([0.5], 100));
  transport.injectControl({ type: "interrupt", mode: "hard" });
  assert.ok(player.calls.includes("hardStop"));
  assert.ok(seen.some((m) => m.type === "interrupt"));
});

test("bargeIn fades when requested and player is active", async () => {
  const { transport, player, session } = makeSession();
  // Inbound audio marks the session as actively playing.
  transport.injectInbound(frame([0.5], 100));
  await session.bargeIn("fade");
  assert.ok(player.calls.includes("fadeOut"));
});

test("bargeIn is a no-op when nothing is playing", async () => {
  const { player, session } = makeSession();
  await session.bargeIn("hard");
  assert.ok(!player.calls.includes("hardStop"));
});

test("stop stops capture, ends + closes transport, hard-stops player", async () => {
  const { capture, transport, player, session } = makeSession();
  await session.start();
  await session.stop();
  assert.equal(capture.stopped, 1);
  assert.equal(transport.ended, 1);
  assert.equal(transport.closed, 1);
  assert.ok(player.calls.includes("hardStop"));
  assert.equal(session.currentState, "stopped");
});

test("telemetry reports send + receive jitter and counters", () => {
  const { transport, session } = makeSession();
  session.send(frame([0], 1000));
  session.send(frame([0], 1030));
  session.send(frame([0], 1050));
  transport.injectInbound(frame([0], 2000));
  transport.injectInbound(frame([0], 2040));
  const t = session.telemetry();
  assert.ok(t.sendJitterMs > 0, "send jitter should be estimated");
  assert.ok(t.receiveJitterMs > 0, "receive jitter should be estimated");
  assert.equal(t.framesSent, 3);
  assert.equal(t.framesReceived, 2);
  assert.equal(t.outboundBufferDepth, 0);
});

test("start is idempotent while running", async () => {
  const { capture, session } = makeSession();
  await session.start();
  await session.start();
  assert.equal(capture.started, 1);
});

test("beginPlaybackTurn delegates to the player", () => {
  const { player, session } = makeSession();
  session.beginPlaybackTurn();
  assert.ok(player.calls.includes("beginTurn"));
});
