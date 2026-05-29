/**
 * SoulYatri Speech — Main Page
 *
 * The primary entry point for the voice AI interface.
 */

"use client";

import VoiceInterface from "@/components/VoiceInterface";

export default function Home() {
  return (
    <main
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        padding: "var(--space-xl) var(--space-md)",
      }}
    >
      <VoiceInterface />
    </main>
  );
}
