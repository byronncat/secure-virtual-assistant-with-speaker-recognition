"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type RecordingStatus = "idle" | "requesting" | "recording" | "error";

interface UseVoiceRecorderOptions {
  onStatusChange?: (status: RecordingStatus) => void;
  /** Called with raw 16-bit PCM bytes and the sample rate they were captured at. */
  onRecordingComplete?: (pcm: ArrayBuffer, sampleRate: number) => void;
}

/**
 * Captures raw PCM audio via the Web Audio API (AudioWorklet) rather than
 * MediaRecorder, so the backend receives uncompressed samples instead of a
 * WebM/Opus container. Matches the pipeline:
 *
 *   Browser (raw PCM @ device rate, ~48kHz) -> FastAPI -> resample to 16kHz
 *   -> Whisper (ASR) + ECAPA-TDNN (speaker verification)
 */
export function useVoiceRecorder({
  onStatusChange,
  onRecordingComplete,
}: UseVoiceRecorderOptions = {}) {
  const [isActive, setIsActive] = useState(false);

  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Float32Array[]>([]);

  const updateStatus = useCallback(
    (status: RecordingStatus) => onStatusChange?.(status),
    [onStatusChange],
  );

  const cleanup = useCallback(() => {
    sourceRef.current?.disconnect();
    workletNodeRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close();
    }
    audioContextRef.current = null;
    workletNodeRef.current = null;
    sourceRef.current = null;
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    if (audioContextRef.current) return; // already recording

    updateStatus("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      streamRef.current = stream;

      // Browsers largely ignore a requested `sampleRate` for microphone
      // input (it runs at the hardware's native rate, commonly 48kHz) —
      // so instead of forcing a rate, we read the *actual* rate off the
      // context afterwards and send it to the backend to resample from.
      const audioContext = new AudioContext();
      audioContextRef.current = audioContext;

      await audioContext.audioWorklet.addModule("/pcm-worklet-processor.js");

      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;

      const workletNode = new AudioWorkletNode(audioContext, "pcm-processor");
      workletNodeRef.current = workletNode;

      chunksRef.current = [];
      workletNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
        chunksRef.current.push(event.data);
      };

      // Deliberately not connected to `audioContext.destination` — we
      // don't want to play the mic input back out of the speakers.
      source.connect(workletNode);

      setIsActive(true);
      updateStatus("recording");
    } catch (err) {
      console.error("Failed to start raw PCM recording:", err);
      cleanup();
      setIsActive(false);
      updateStatus("error");
    }
  }, [cleanup, updateStatus]);

  const stop = useCallback(() => {
    const sampleRate = audioContextRef.current?.sampleRate ?? 48000;
    cleanup();
    setIsActive(false);

    const chunks = chunksRef.current;
    chunksRef.current = [];

    if (chunks.length === 0) {
      updateStatus("idle");
      return;
    }

    const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    const pcm16 = floatTo16BitPCM(merged);
    updateStatus("idle");

    const buffer = new ArrayBuffer(pcm16.byteLength);
    new Int16Array(buffer).set(pcm16);
    onRecordingComplete?.(buffer, sampleRate);
  }, [cleanup, onRecordingComplete, updateStatus]);

  // Guard against a stuck-open mic if the component unmounts mid-recording.
  useEffect(() => cleanup, [cleanup]);

  return { isActive, start, stop };
}

function floatTo16BitPCM(float32Array: Float32Array): Int16Array {
  const output = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}
