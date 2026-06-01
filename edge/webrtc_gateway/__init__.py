"""edge/webrtc_gateway/ — WebRTC + Opus ingress and session metadata (final_use.md §4, Phase 2B).

Owner: edge/runtime agent. Handles realtime transport ingest, reconnects, jitter
smoothing, and routing of audio frames to the runtime. Complements the existing
WebSocket PCM path in server/main.py during bring-up.
"""
