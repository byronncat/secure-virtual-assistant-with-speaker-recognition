"use client";

import { useCallback, useState } from "react";
import clsx from "clsx";
import { AlertTriangle, Mic } from "lucide-react";
import ControlBar from "../widgets/ControlBar";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { sendVoiceClip, ApiError, type PipelineResult } from "@/lib/api";

export default function CenterPanel() {
  const [language, setLanguage] = useState("en");
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [lastResult, setLastResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { status, start, stop } = useVoiceRecorder();

  const handleStop = useCallback(async () => {
    const result = stop();
    if (!result) return;

    setStreamingAnswer("");
    setLastResult(null);
    setError(null);

    try {
      await sendVoiceClip(result.pcm, result.sampleRate, language, {
        onAnswerChunk: (chunk) => setStreamingAnswer((prev) => prev + chunk),
        onDone: (result: PipelineResult) => {
          setLastResult(result);
          setStreamingAnswer("");
        },
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Voice request failed.");
    }
  }, [stop, language]);

  return (
    <section
      className={clsx(
        "relative size-full",
        "flex flex-col items-center justify-between",
        "px-8 py-10",
      )}
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-10">
        <MicButton
          isActive={status === "recording"}
          onStart={start}
          onStop={handleStop}
        />

        <div
          className={clsx(
            "relative z-10 text-center",
            "flex flex-col items-center gap-2",
          )}
        >
          <h1 className="text-[30px] font-semibold">{statusHeading(status)}</h1>
          <p className="text-[16px] text-faint max-w-[420px]">
            {statusSubtext(status, streamingAnswer, lastResult)}
          </p>
          {lastResult?.rejected && (
            <p className="flex items-center gap-1.5 text-[13px] text-red-400">
              <AlertTriangle size={14} strokeWidth={2} />
              Command &ldquo;{lastResult.command}&rdquo; was rejected
              {lastResult.speaker_id
                ? ` (speaker: ${lastResult.speaker_id})`
                : ""}
              .
            </p>
          )}
          {error && <p className="text-[13px] text-red-400">{error}</p>}
        </div>
      </div>

      <ControlBar language={language} onLanguageChange={setLanguage} />
    </section>
  );
}

function statusHeading(status: string) {
  switch (status) {
    case "recording":
      return "Listening...";
    case "requesting":
      return "One sec...";
    case "processing":
      return "Processing...";
    case "error":
      return "Mic unavailable";
    default:
      return "Tap to Speak";
  }
}

function statusSubtext(
  status: string,
  streamingAnswer: string,
  lastResult: PipelineResult | null,
) {
  switch (status) {
    case "recording":
      return "I'm listening...";
    case "requesting":
      return "Requesting mic access";
    case "processing":
      return "Working on it...";
    case "error":
      return "Check your microphone permissions";
    default:
      if (streamingAnswer) return streamingAnswer;
      if (lastResult?.answer) return lastResult.answer;
      if (lastResult?.text) return lastResult.text;
      return "Press and hold the mic to talk";
  }
}

interface MicButtonProps {
  isActive: boolean;
  onStart: () => void;
  onStop: () => void;
}

function MicButton({ isActive, onStart, onStop }: MicButtonProps) {
  return (
    <button
      type="button"
      aria-label="Mic button"
      aria-pressed={isActive}
      className={clsx(
        "relative size-50 rounded-full",
        "flex items-center justify-center",
        "transition-colors ease-in-out cursor-pointer",
        isActive
          ? "bg-primary pulse"
          : "hover:bg-primary/50 border-2 border-primary",
      )}
      onPointerDown={onStart}
      onPointerUp={onStop}
      onPointerLeave={() => {
        if (isActive) onStop();
      }}
    >
      <Mic
        size={60}
        strokeWidth={1.5}
        className="text-white/95 relative z-10"
      />
      {Array.from({ length: 4 }, (_, i) => (
        <span key={i} style={{ "--i": i } as React.CSSProperties} />
      ))}
    </button>
  );
}
