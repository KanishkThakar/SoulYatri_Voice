"use client";

import React, { useState } from "react";
import AudioVisualizer from "./AudioVisualizer";
import ConnectionStatus from "./ConnectionStatus";
import TranscriptPanel from "./TranscriptPanel";
import { useVoiceStream } from "@/hooks/useVoiceStream";
import styles from "./VoiceInterface.module.css";

export default function VoiceInterface() {
  const {
    connectionState,
    isRecording,
    audioLevel,
    transcripts,
    lastAudioSource,
    turnMetadata,
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
      return;
    }

    if (connectionState !== "connected") {
      connect();
      await new Promise((resolve) => setTimeout(resolve, 500));
    }

    startRecording();
  };

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <div className={styles.titleGroup}>
          <h1 className={styles.title}>
            <span className="text-gradient">SoulYatri</span>
          </h1>
          <p className={styles.subtitle}>
            Voice AI — Talk naturally in Hindi, English, or Hinglish
          </p>
        </div>

        <ConnectionStatus state={connectionState} />
      </div>

      <div className={styles.visualizerSection}>
        {isRecording && <div className={styles.ambientPulse} />}

        <AudioVisualizer audioLevel={audioLevel} isActive={isRecording} size={240} />

        <p className={`${styles.statusText} ${isRecording ? styles.statusTextActive : ""}`}>
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

      <div className={styles.controls}>
        <button
          id="mic-toggle-btn"
          onClick={handleMicToggle}
          className={`${styles.micButton} btn ${isRecording ? "btn-danger" : "btn-primary"}`}
          aria-label={isRecording ? "Stop recording" : "Start recording"}
        >
          {isRecording && (
            <>
              <span className={styles.micRipple} />
              <span className={`${styles.micRipple} ${styles.micRippleDelayed}`} />
            </>
          )}
          <span className={styles.micButtonIcon}>{isRecording ? "⏹" : "🎤"}</span>
        </button>

        {connectionState === "connected" && (
          <button
            id="disconnect-btn"
            onClick={disconnect}
            className="btn btn-ghost"
          >
            Disconnect
          </button>
        )}

        <button
          id="transcript-toggle-btn"
          onClick={() => setShowTranscript(!showTranscript)}
          className="btn btn-ghost"
        >
          {showTranscript ? "Hide" : "Show"} Transcript
        </button>
      </div>

      {(lastAudioSource || turnMetadata) && (
        <div className={styles.metaRow}>
          {lastAudioSource && (
            <span className={styles.chip}>
              Playback: {lastAudioSource === "filler" ? "filler" : "response"}
            </span>
          )}
          {turnMetadata?.emotion?.label && (
            <span className={styles.chip}>
              Emotion: {turnMetadata.emotion.label}
            </span>
          )}
          {turnMetadata?.speaker_embedding_id && (
            <span className={styles.chip}>
              Speaker: {turnMetadata.speaker_embedding_id}
            </span>
          )}
          {turnMetadata?.barge_in && (
            <span className={styles.chip}>Barge-in detected</span>
          )}
        </div>
      )}

      {showTranscript && (
        <div className={`${styles.transcriptCard} glass-card`}>
          <TranscriptPanel transcripts={transcripts} onClear={clearTranscripts} />
        </div>
      )}

      <div className={styles.footer}>
        <span>Phase 2 • Turn state + filler + features</span>
        <span>•</span>
        <span>{connectionState === "connected" ? "🟢" : "⚫"} WebSocket</span>
      </div>
    </div>
  );
}
