# client/audio

Owner: client agent (final_use.md §4, §7.1, Phase 2A/2B).

Capture, AEC/noise suppression, and realtime transport for the Next.js client.
Keep frame sizes small and buffers short. TypeScript modules (not a Python package).

Implemented modules:
- `types.ts` — `AudioFrame` + PCM16/float32/wire converters + linear resampler (DOM-free).
- `capture.ts` — **2A** mic PCM capture, AEC/NS/AGC via getUserMedia constraints,
  device selection + permissions, AudioWorklet (ScriptProcessor fallback), target sample rate.
- `webrtc.ts` — **2B** reconnect-survivable realtime transport (`RealtimeTransportClient`)
  with a pluggable `Transport` (`WebSocketTransport`, `LoopbackTransport`; WebRTC/Opus/LiveKit
  plug in behind the same interface).
- `index.ts` — barrel.

Design note: `client/src/README.md`. Server-side transport counterpart:
`edge/webrtc_gateway/`. The existing `client/src/hooks/useVoiceStream.ts` remains
the current bring-up implementation and is unchanged.
