/**
 * SoulYatri Speech — Connection Status Component
 *
 * Displays the current connection state with animated indicators
 * and contextual messaging.
 */

"use client";

import React from "react";
import type { ConnectionState } from "@/hooks/useVoiceStream";

interface ConnectionStatusProps {
  state: ConnectionState;
}

const stateConfig: Record<
  ConnectionState,
  { label: string; color: string; dotClass: string }
> = {
  disconnected: {
    label: "Disconnected",
    color: "var(--color-text-muted)",
    dotClass: "disconnected",
  },
  connecting: {
    label: "Connecting...",
    color: "var(--color-accent-warm)",
    dotClass: "connecting",
  },
  connected: {
    label: "Connected",
    color: "var(--color-accent-success)",
    dotClass: "connected",
  },
  error: {
    label: "Connection Error",
    color: "var(--color-accent-danger)",
    dotClass: "disconnected",
  },
};

export default function ConnectionStatus({ state }: ConnectionStatusProps) {
  const config = stateConfig[state];

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-sm)",
        padding: "var(--space-xs) var(--space-md)",
        borderRadius: "var(--radius-full)",
        background: "var(--color-bg-glass)",
        backdropFilter: "blur(10px)",
        border: "1px solid var(--color-border)",
        fontSize: "0.8rem",
        fontWeight: 500,
        color: config.color,
        transition: "all var(--transition-normal)",
      }}
    >
      <span className={`status-dot ${config.dotClass}`} />
      <span>{config.label}</span>
    </div>
  );
}
