/**
 * SoulYatri Speech — Transcript Panel Component
 *
 * Displays the live conversation transcript with user and AI messages,
 * auto-scrolling to the latest message.
 */

"use client";

import React, { useRef, useEffect } from "react";
import type { TranscriptEntry } from "@/hooks/useVoiceStream";

interface TranscriptPanelProps {
  transcripts: TranscriptEntry[];
  onClear?: () => void;
}

export default function TranscriptPanel({
  transcripts,
  onClear,
}: TranscriptPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new transcripts arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcripts]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        maxHeight: "400px",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "var(--space-md) var(--space-lg)",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <h3
          style={{
            fontSize: "0.85rem",
            fontWeight: 600,
            color: "var(--color-text-secondary)",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          Conversation
        </h3>

        {transcripts.length > 0 && onClear && (
          <button
            onClick={onClear}
            className="btn btn-ghost"
            style={{ padding: "2px 10px", fontSize: "0.75rem" }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflow: "auto",
          padding: "var(--space-md) var(--space-lg)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-md)",
        }}
      >
        {transcripts.length === 0 ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              color: "var(--color-text-muted)",
              fontSize: "0.85rem",
              fontStyle: "italic",
            }}
          >
            Start speaking to begin the conversation...
          </div>
        ) : (
          transcripts.map((entry) => (
            <div
              key={entry.id}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: entry.role === "user" ? "flex-end" : "flex-start",
                animation: "fadeIn 0.3s ease-out",
              }}
            >
              {/* Role label */}
              <span
                style={{
                  fontSize: "0.7rem",
                  fontWeight: 600,
                  color:
                    entry.role === "user"
                      ? "var(--color-accent-info)"
                      : "var(--color-accent-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  marginBottom: "4px",
                  paddingLeft: entry.role === "assistant" ? "12px" : 0,
                  paddingRight: entry.role === "user" ? "12px" : 0,
                }}
              >
                {entry.role === "user" ? "You" : "SoulYatri"}
              </span>

              {/* Message bubble */}
              <div
                style={{
                  maxWidth: "85%",
                  padding: "var(--space-sm) var(--space-md)",
                  borderRadius:
                    entry.role === "user"
                      ? "var(--radius-lg) var(--radius-lg) 4px var(--radius-lg)"
                      : "var(--radius-lg) var(--radius-lg) var(--radius-lg) 4px",
                  background:
                    entry.role === "user"
                      ? "rgba(59, 130, 246, 0.15)"
                      : "rgba(168, 85, 247, 0.12)",
                  border: `1px solid ${
                    entry.role === "user"
                      ? "rgba(59, 130, 246, 0.2)"
                      : "rgba(168, 85, 247, 0.2)"
                  }`,
                  color: "var(--color-text-primary)",
                  fontSize: "0.9rem",
                  lineHeight: 1.5,
                }}
              >
                {entry.text}
              </div>

              {/* Timestamp */}
              <span
                className="font-mono"
                style={{
                  fontSize: "0.65rem",
                  color: "var(--color-text-muted)",
                  marginTop: "2px",
                  paddingLeft: entry.role === "assistant" ? "12px" : 0,
                  paddingRight: entry.role === "user" ? "12px" : 0,
                }}
              >
                {new Date(entry.timestamp).toLocaleTimeString()}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
