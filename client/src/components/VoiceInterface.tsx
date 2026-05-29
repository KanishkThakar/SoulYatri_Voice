/**
 * SoulYatri Speech — Voice Interface Component
 *
 * The main voice interaction UI combining the visualizer,
 * controls, and transcript panel into a cohesive experience.
 */

"use client";

import React, { useState } from "react";
import AudioVisualizer from "./AudioVisualizer";
import ConnectionStatus from "./ConnectionStatus";
import TranscriptPanel from "./TranscriptPanel";
import { useVoiceStream } from "@/hooks/useVoiceStream";

export default function VoiceInterface() {
  const {
    connectionState,
    isRecording,
    audioLevel,
    transcripts,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    clearTranscripts,
  } = useVoiceStream({
    serverUrl: "ws://localhost:8000/ws/audio",
    sampleRate: 16000,
  });

  const [showTranscript, setShowTranscript] = useState(true);

  const handleMicToggle = async () => {
    if (isRecording) {
      stopRecording();
    } else {
      if (connectionState !== "connected") {
        connect();
        // Small delay to let WS connect
        await new Promise((r) => setTimeout(r, 500));
      }
      startRecording();
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: "100%",
        maxWidth: "800px",
        margin: "0 auto",
        gap: "var(--space-xl)",
        animation: "fadeIn 0.6s ease-out",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          width: "100%",
          padding: "0 var(--space-md)",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: "1.8rem",
              fontWeight: 800,
              letterSpacing: "-0.02em",
              marginBottom: "4px",
            }}
          >
            <span className="text-gradient">SoulYatri</span>
          </h1>
          <p
            style={{
              fontSize: "0.85rem",
              color: "var(--color-text-muted)",
              fontWeight: 400,
            }}
          >
            Voice AI — Talk naturally in Hindi, English, or Hinglish
          </p>
        </div>

        <ConnectionStatus state={connectionState} />
      </div>

      {/* Visualizer Area */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "300px",
          width: "100%",
          position: "relative",
        }}
      >
        {/* Ambient background pulse */}
        {isRecording && (
          <div
            style={{
              position: "absolute",
              width: "350px",
              height: "350px",
              borderRadius: "50%",
              background:
                "radial-gradient(circle, rgba(124, 58, 237, 0.08) 0%, transparent 70%)",
              animation: "breathe 3s ease-in-out infinite",
              pointerEvents: "none",
            }}
          />
        )}

        <AudioVisualizer
          audioLevel={audioLevel}
          isActive={isRecording}
          size={240}
        />

        {/* Status text below visualizer */}
        <p
          style={{
            marginTop: "var(--space-lg)",
            fontSize: "0.9rem",
            color: isRecording
              ? "var(--color-text-accent)"
              : "var(--color-text-muted)",
            fontWeight: 500,
            transition: "color var(--transition-normal)",
          }}
        >
          {isRecording
            ? "Listening..."
            : connectionState === "connected"
              ? "Tap the mic to start"
              : connectionState === "connecting"
                ? "Connecting to server..."
                : connectionState === "error"
                  ? "Connection failed — is the server running?"
                  : "Tap the mic to connect and start"}
        </p>
      </div>

      {/* Controls */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-lg)",
        }}
      >
        {/* Mic button */}
        <button
          id="mic-toggle-btn"
          onClick={handleMicToggle}
          className="btn"
          style={{
            width: 72,
            height: 72,
            borderRadius: "50%",
            fontSize: "1.5rem",
            background: isRecording
              ? "var(--color-accent-danger)"
              : "var(--gradient-primary)",
            color: "white",
            boxShadow: isRecording
              ? "0 0 30px rgba(239, 68, 68, 0.4)"
              : "var(--shadow-md), var(--shadow-glow)",
            transition: "all var(--transition-normal)",
            position: "relative",
            overflow: "hidden",
          }}
          aria-label={isRecording ? "Stop recording" : "Start recording"}
        >
          {/* Ripple effect when recording */}
          {isRecording && (
            <>
              <span
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: "50%",
                  border: "2px solid rgba(255,255,255,0.3)",
                  animation: "ripple 2s ease-out infinite",
                }}
              />
              <span
                style={{
                  position: "absolute",
                  inset: 0,
                  borderRadius: "50%",
                  border: "2px solid rgba(255,255,255,0.2)",
                  animation: "ripple 2s ease-out infinite 0.5s",
                }}
              />
            </>
          )}
          {isRecording ? "⏹" : "🎤"}
        </button>

        {/* Disconnect button */}
        {connectionState === "connected" && (
          <button
            id="disconnect-btn"
            onClick={disconnect}
            className="btn btn-ghost"
            style={{
              padding: "var(--space-sm) var(--space-lg)",
              animation: "fadeIn 0.3s ease-out",
            }}
          >
            Disconnect
          </button>
        )}

        {/* Toggle transcript */}
        <button
          id="transcript-toggle-btn"
          onClick={() => setShowTranscript(!showTranscript)}
          className="btn btn-ghost"
          style={{ padding: "var(--space-sm) var(--space-lg)" }}
        >
          {showTranscript ? "Hide" : "Show"} Transcript
        </button>
      </div>

      {/* Transcript Panel */}
      {showTranscript && (
        <div
          className="glass-card"
          style={{
            width: "100%",
            overflow: "hidden",
            animation: "slideUp 0.4s ease-out",
          }}
        >
          <TranscriptPanel
            transcripts={transcripts}
            onClear={clearTranscripts}
          />
        </div>
      )}

      {/* Footer info */}
      <div
        style={{
          display: "flex",
          gap: "var(--space-lg)",
          fontSize: "0.75rem",
          color: "var(--color-text-muted)",
          fontFamily: "var(--font-mono)",
        }}
      >
        <span>Phase 1 • STT→LLM→TTS Pipeline</span>
        <span>•</span>
        <span>{connectionState === "connected" ? "🟢" : "⚫"} WebSocket</span>
      </div>
    </div>
  );
}
