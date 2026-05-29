/**
 * SoulYatri Speech — Audio Visualizer Component
 *
 * Canvas-based real-time audio waveform visualization with
 * animated rings and breathing effects.
 */

"use client";

import React, { useRef, useEffect, useCallback } from "react";

interface AudioVisualizerProps {
  audioLevel: number; // 0.0 to 1.0
  isActive: boolean;
  size?: number;
}

export default function AudioVisualizer({
  audioLevel,
  isActive,
  size = 240,
}: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number>(0);
  const smoothLevelRef = useRef(0);
  const timeRef = useRef(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = size * dpr;
    const h = size * dpr;

    canvas.width = w;
    canvas.height = h;

    const cx = w / 2;
    const cy = h / 2;

    // Smooth the audio level
    const target = isActive ? audioLevel : 0;
    smoothLevelRef.current += (target - smoothLevelRef.current) * 0.15;
    const level = smoothLevelRef.current;

    timeRef.current += 0.02;
    const t = timeRef.current;

    // Clear
    ctx.clearRect(0, 0, w, h);

    // --- Outer ambient glow ---
    if (isActive) {
      const glowRadius = (w * 0.4) + level * w * 0.1;
      const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius);
      gradient.addColorStop(0, `rgba(124, 58, 237, ${0.08 + level * 0.12})`);
      gradient.addColorStop(0.5, `rgba(168, 85, 247, ${0.04 + level * 0.06})`);
      gradient.addColorStop(1, "rgba(124, 58, 237, 0)");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, w, h);
    }

    // --- Concentric rings ---
    const ringCount = 4;
    for (let i = 0; i < ringCount; i++) {
      const baseRadius = w * 0.12 + i * w * 0.06;
      const waveAmp = isActive ? level * w * 0.04 * (1 - i * 0.2) : w * 0.005;
      const radius = baseRadius + Math.sin(t * (1.5 - i * 0.3)) * waveAmp;

      const alpha = isActive
        ? 0.15 + level * 0.2 - i * 0.03
        : 0.06 - i * 0.01;

      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(168, 85, 247, ${Math.max(alpha, 0.02)})`;
      ctx.lineWidth = isActive ? 1.5 + level * 2 : 1;
      ctx.stroke();
    }

    // --- Main circle ---
    const mainRadius = w * 0.1 + (isActive ? level * w * 0.05 : Math.sin(t * 0.8) * w * 0.005);

    // Glow behind main circle
    const mainGlow = ctx.createRadialGradient(cx, cy, mainRadius * 0.5, cx, cy, mainRadius * 1.8);
    mainGlow.addColorStop(0, `rgba(124, 58, 237, ${isActive ? 0.3 + level * 0.3 : 0.1})`);
    mainGlow.addColorStop(1, "rgba(124, 58, 237, 0)");
    ctx.fillStyle = mainGlow;
    ctx.fillRect(0, 0, w, h);

    // Main circle fill
    const circleGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, mainRadius);
    circleGrad.addColorStop(0, isActive ? "rgba(168, 85, 247, 0.9)" : "rgba(124, 58, 237, 0.4)");
    circleGrad.addColorStop(1, isActive ? "rgba(124, 58, 237, 0.6)" : "rgba(124, 58, 237, 0.2)");

    ctx.beginPath();
    ctx.arc(cx, cy, mainRadius, 0, Math.PI * 2);
    ctx.fillStyle = circleGrad;
    ctx.fill();

    // Main circle border
    ctx.strokeStyle = `rgba(196, 181, 253, ${isActive ? 0.5 + level * 0.3 : 0.2})`;
    ctx.lineWidth = 2;
    ctx.stroke();

    // --- Wave bars (when active) ---
    if (isActive && level > 0.01) {
      const barCount = 24;
      const barWidth = 2.5 * dpr;

      for (let i = 0; i < barCount; i++) {
        const angle = (i / barCount) * Math.PI * 2;
        const barLevel = level * (0.5 + 0.5 * Math.sin(t * 3 + i * 0.5));
        const barHeight = w * 0.03 + barLevel * w * 0.08;

        const innerR = mainRadius + 4 * dpr;
        const outerR = innerR + barHeight;

        const x1 = cx + Math.cos(angle) * innerR;
        const y1 = cy + Math.sin(angle) * innerR;
        const x2 = cx + Math.cos(angle) * outerR;
        const y2 = cy + Math.sin(angle) * outerR;

        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = `rgba(196, 181, 253, ${0.4 + barLevel * 0.4})`;
        ctx.lineWidth = barWidth;
        ctx.lineCap = "round";
        ctx.stroke();
      }
    }

    // --- Center icon ---
    const iconSize = mainRadius * 0.5;
    ctx.fillStyle = `rgba(255, 255, 255, ${isActive ? 0.9 : 0.5})`;
    ctx.font = `${iconSize}px Inter`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(isActive ? "🎙️" : "🎤", cx, cy);

    animFrameRef.current = requestAnimationFrame(draw);
  }, [audioLevel, isActive, size]);

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
      }}
    />
  );
}
