# client/playback

Owner: client agent (final_use.md §4, §7.1, Phase 2C).

Streaming PCM playback that starts quickly and stops cleanly on interruption
(fadeout/hard-cut). TypeScript modules.

Implemented modules:
- `stream_player.ts` — **2C** `StreamPlayer`: gapless chunk scheduling on the
  AudioContext clock, inbound jitter reorder buffer, `fadeOut()` (clean soft stop)
  and `hardStop()` (instant barge-in cancel).
- `index.ts` — barrel.

Design note: `client/src/README.md`.
