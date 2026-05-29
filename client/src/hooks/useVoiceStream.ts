/**
 * SoulYatri Speech — WebSocket Audio Hook
 *
 * Custom hook for managing WebSocket connection to the Python backend
 * for real-time audio streaming. Handles microphone capture, audio
 * transmission, and response playback.
 */

"use client";

import { useState, useRef, useCallback, useEffect } from "react";

export type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

export interface TranscriptEntry {
  id: string;
  role: "user" | "assistant";
  text: string;
  timestamp: number;
}

interface UseVoiceStreamOptions {
  serverUrl?: string;
  sampleRate?: number;
  onTranscript?: (entry: TranscriptEntry) => void;
  onAudioResponse?: (audioData: ArrayBuffer, sampleRate: number) => void;
  onConnectionChange?: (state: ConnectionState) => void;
}

export function useVoiceStream(options: UseVoiceStreamOptions = {}) {
  const {
    serverUrl = "ws://localhost:8000/ws/audio",
    sampleRate = 16000,
    onTranscript,
    onAudioResponse,
    onConnectionChange,
  } = options;

  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number>(0);
  const sessionIdRef = useRef<string>(`session-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const playbackContextRef = useRef<AudioContext | null>(null);

  // Update connection state with callback
  const updateConnectionState = useCallback(
    (state: ConnectionState) => {
      setConnectionState(state);
      onConnectionChange?.(state);
    },
    [onConnectionChange]
  );

  // Add transcript entry
  const addTranscript = useCallback(
    (role: "user" | "assistant", text: string) => {
      const entry: TranscriptEntry = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        role,
        text,
        timestamp: Date.now(),
      };
      setTranscripts((prev) => [...prev, entry]);
      onTranscript?.(entry);
    },
    [onTranscript]
  );

  // Play received audio
  const playAudio = useCallback(
    async (audioData: ArrayBuffer, responseSampleRate: number) => {
      try {
        if (!playbackContextRef.current) {
          playbackContextRef.current = new AudioContext();
        }

        const ctx = playbackContextRef.current;

        // Create audio buffer from raw PCM (16-bit signed integer)
        const int16Array = new Int16Array(audioData);
        const float32Array = new Float32Array(int16Array.length);

        for (let i = 0; i < int16Array.length; i++) {
          float32Array[i] = int16Array[i] / 32768.0;
        }

        const audioBuffer = ctx.createBuffer(1, float32Array.length, responseSampleRate);
        audioBuffer.getChannelData(0).set(float32Array);

        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        source.start();

        onAudioResponse?.(audioData, responseSampleRate);
      } catch (err) {
        console.error("Audio playback error:", err);
      }
    },
    [onAudioResponse]
  );

  // Connect WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    updateConnectionState("connecting");
    const sessionId = sessionIdRef.current;
    const ws = new WebSocket(`${serverUrl}/${sessionId}`);

    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      updateConnectionState("connected");
      // Send config
      ws.send(JSON.stringify({ type: "config", sample_rate: sampleRate }));
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        // Binary: audio response
        playAudio(event.data, 24000); // edge-tts outputs 24kHz
      } else {
        // Text: control message
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "transcript") {
            addTranscript(msg.role, msg.text);
          } else if (msg.type === "audio_meta") {
            // Audio metadata — used for future sync
          }
        } catch {
          // Ignore parse errors
        }
      }
    };

    ws.onerror = () => {
      updateConnectionState("error");
    };

    ws.onclose = () => {
      updateConnectionState("disconnected");
      setIsRecording(false);
    };

    wsRef.current = ws;
  }, [serverUrl, sampleRate, updateConnectionState, addTranscript, playAudio]);

  // Start recording
  const startRecording = useCallback(async () => {
    try {
      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: sampleRate,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      mediaStreamRef.current = stream;

      // Create audio context
      const audioContext = new AudioContext({ sampleRate });
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);

      // Analyser for level metering
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Processor for sending audio to WebSocket
      // Using ScriptProcessorNode (deprecated but widely supported)
      // TODO: Migrate to AudioWorklet for production
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = (e) => {
        if (wsRef.current?.readyState !== WebSocket.OPEN) return;

        const inputData = e.inputBuffer.getChannelData(0);

        // Convert float32 to int16 PCM
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }

        wsRef.current.send(pcmData.buffer);
      };

      source.connect(processor);
      processor.connect(audioContext.destination);
      processorRef.current = processor;

      // Start audio level monitoring
      const updateLevel = () => {
        if (!analyserRef.current) return;
        const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b) / dataArray.length;
        setAudioLevel(avg / 255);
        animFrameRef.current = requestAnimationFrame(updateLevel);
      };
      updateLevel();

      setIsRecording(true);

      // Auto-connect WebSocket if not already
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        connect();
      }
    } catch (err) {
      console.error("Microphone access error:", err);
      updateConnectionState("error");
    }
  }, [sampleRate, connect, updateConnectionState]);

  // Stop recording
  const stopRecording = useCallback(() => {
    // Stop animation frame
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
    }

    // Disconnect processor
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    // Close audio context
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    // Stop media stream
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    analyserRef.current = null;
    setIsRecording(false);
    setAudioLevel(0);
  }, []);

  // Disconnect everything
  const disconnect = useCallback(() => {
    stopRecording();

    if (wsRef.current) {
      wsRef.current.send(JSON.stringify({ type: "end" }));
      wsRef.current.close();
      wsRef.current = null;
    }

    if (playbackContextRef.current) {
      playbackContextRef.current.close();
      playbackContextRef.current = null;
    }

    updateConnectionState("disconnected");
  }, [stopRecording, updateConnectionState]);

  // Clear transcripts
  const clearTranscripts = useCallback(() => {
    setTranscripts([]);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    connectionState,
    isRecording,
    audioLevel,
    transcripts,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    clearTranscripts,
  };
}
