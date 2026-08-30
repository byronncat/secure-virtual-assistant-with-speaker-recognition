"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Mic } from "lucide-react";
import ControlBar from "./ControlBar";

export default function CenterPanel() {
  const [status, setStatus] = useState<RecordingStatus>("idle");

  return (
    <section
      className={clsx(
        "relative flex size-full flex-col items-center justify-between",
        "px-8 py-10",
      )}
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-10">
        <MicButton
          onStatusChange={setStatus}
          onRecordingComplete={(blob) => {
            // Wire this up to your upload / transcription pipeline.
            console.log("Recording complete:", blob);
          }}
        />

        <div
          className={clsx(
            "flex flex-col items-center",
            "gap-2 text-center",
            "relative z-10",
          )}
        >
          <h1 className="text-[30px] font-semibold">{statusHeading(status)}</h1>
          <p className="text-[16px] text-faint">{statusSubtext(status)}</p>
        </div>
      </div>

      <ControlBar />
    </section>
  );
}

type RecordingStatus = "idle" | "requesting" | "recording" | "error";

function statusHeading(status: RecordingStatus) {
  switch (status) {
    case "recording":
      return "Listening...";
    case "requesting":
      return "One sec...";
    case "error":
      return "Mic unavailable";
    default:
      return "Tap to Speak";
  }
}

function statusSubtext(status: RecordingStatus) {
  switch (status) {
    case "recording":
      return "I'm listening...";
    case "requesting":
      return "Requesting mic access";
    case "error":
      return "Check your microphone permissions";
    default:
      return "Press and hold the mic to talk";
  }
}

interface MicButtonProps {
  onStatusChange?: (status: RecordingStatus) => void;
  onRecordingComplete?: (blob: Blob) => void;
}

function MicButton({ onStatusChange, onRecordingComplete }: MicButtonProps) {
  const [isActive, setIsActive] = useState(false);
  const [status, setStatus] = useState<RecordingStatus>("idle");

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const updateStatus = useCallback(
    (next: RecordingStatus) => {
      setStatus(next);
      onStatusChange?.(next);
    },
    [onStatusChange],
  );

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const startRecording = useCallback(async () => {
    // Guard against double-starts (e.g. rapid pointer events).
    if (recorderRef.current && recorderRef.current.state !== "inactive") return;

    updateStatus("requesting");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : undefined; // let the browser pick a supported default (e.g. Safari)

      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined,
      );
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        chunksRef.current = [];
        stopStream();
        onRecordingComplete?.(blob);
      };

      recorder.onerror = () => {
        updateStatus("error");
        stopStream();
      };

      recorderRef.current = recorder;
      recorder.start();
      setIsActive(true);
      updateStatus("recording");
    } catch (err) {
      console.error("Mic access failed:", err);
      updateStatus("error");
      setIsActive(false);
    }
  }, [onRecordingComplete, stopStream, updateStatus]);

  const stopRecording = useCallback(() => {
    setIsActive(false);
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    } else {
      stopStream();
    }
    if (status !== "error") updateStatus("idle");
  }, [status, stopStream, updateStatus]);

  // Clean up if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
      stopStream();
    };
  }, [stopStream]);

  return (
    <button
      type="button"
      aria-label="Mic button"
      aria-pressed={isActive}
      className={clsx(
        "relative size-50 rounded-full",
        "flex items-center justify-center",
        "transition-colors duration-150 ease-in-out cursor-pointer",
        isActive
          ? "bg-primary pulse"
          : "hover:bg-primary/50 border-2 border-primary bg-primary/30",
      )}
      onPointerDown={startRecording}
      onPointerUp={stopRecording}
      onPointerLeave={() => {
        if (isActive) stopRecording();
      }}
    >
      <Mic
        size={60}
        strokeWidth={1.5}
        className="text-white/95 relative z-50"
      />
      {Array.from({ length: 4 }, (_, i) => (
        <span key={i} style={{ "--i": i } as React.CSSProperties} />
      ))}
    </button>
  );
}
