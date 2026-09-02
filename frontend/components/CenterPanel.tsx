"use client";

import { useCallback, useState } from "react";
import clsx from "clsx";
import { Mic } from "lucide-react";
import ControlBar from "./ControlBar";
import {
  useVoiceRecorder,
  type RecordingStatus,
} from "@/hooks/useVoiceRecorder";

const VOICE_ENDPOINT = "http://localhost:8000/api/voice";

// Matches the unified response contract from the backend's `done` SSE
// event (pipeline.py / main.py): {text, language, speaker_id, command,
// rejected, answer}. `answer` arrives incrementally via `answer_chunk`
// events before that, so the UI can show it streaming in.
interface PipelineResult {
  text: string;
  language: string | null;
  speaker_id: string | null;
  command: string | null;
  rejected: boolean;
  answer: string;
}

/**
 * Parses one SSE frame of the form:
 *   event: <type>\n
 *   data: <json>\n\n
 * Returns null if the frame doesn't contain a recognizable event.
 */
function parseSseFrame(frame: string): { type: string; data: unknown } | null {
  const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
  const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
  if (!eventLine || !dataLine) return null;
  const type = eventLine.slice("event: ".length).trim();
  try {
    const data = JSON.parse(dataLine.slice("data: ".length));
    return { type, data };
  } catch {
    return null;
  }
}

export default function CenterPanel() {
  const [status, setStatus] = useState<RecordingStatus>("idle");
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [lastResult, setLastResult] = useState<PipelineResult | null>(null);

  const uploadRecording = useCallback(
    async (pcm: ArrayBuffer, sampleRate: number) => {
      const formData = new FormData();
      // Raw 16-bit PCM, little-endian, mono — no container/codec, so the
      // backend just needs to know the sample rate to resample from.
      formData.append(
        "audio",
        new Blob([pcm], { type: "application/octet-stream" }),
        "recording.pcm",
      );
      formData.append("sample_rate", String(sampleRate));
      formData.append("channels", "1");

      setStreamingAnswer("");
      setLastResult(null);

      try {
        const res = await fetch(VOICE_ENDPOINT, {
          method: "POST",
          body: formData,
        });
        if (!res.ok || !res.body) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail ?? `Upload failed (${res.status})`);
        }

        // The backend streams Server-Sent Events: a "meta" event as soon
        // as ASR/correction/intent routing finish, zero or more
        // "answer_chunk" events (conversation replies only), and a final
        // "done" event carrying the full unified result.
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let answerSoFar = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);

            const parsed = parseSseFrame(frame);
            if (!parsed) continue;

            if (parsed.type === "answer_chunk") {
              const { chunk } = parsed.data as { chunk: string };
              answerSoFar += chunk;
              setStreamingAnswer(answerSoFar);
            } else if (parsed.type === "done") {
              const result = parsed.data as PipelineResult;
              setLastResult(result);
              setStreamingAnswer("");
            }
          }
        }
      } catch (err) {
        console.error("Voice upload failed:", err);
        setStatus("error");
      }
    },
    [],
  );

  const { isActive, start, stop } = useVoiceRecorder({
    onStatusChange: setStatus,
    onRecordingComplete: uploadRecording,
  });

  return (
    <section
      className={clsx(
        "relative flex size-full flex-col items-center justify-between",
        "px-8 py-10",
      )}
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-10">
        <MicButton isActive={isActive} onStart={start} onStop={stop} />

        <div
          className={clsx(
            "flex flex-col items-center",
            "gap-2 text-center",
            "relative z-10",
          )}
        >
          <h1 className="text-[30px] font-semibold">{statusHeading(status)}</h1>
          <p className="text-[16px] text-faint">
            {statusSubtext(status, streamingAnswer, lastResult)}
          </p>
          {lastResult?.rejected && (
            <p className="text-[13px] text-red-400">
              Command &ldquo;{lastResult.command}&rdquo; was rejected
              {lastResult.speaker_id
                ? ` (speaker: ${lastResult.speaker_id})`
                : ""}
              .
            </p>
          )}
        </div>
      </div>

      <ControlBar />
    </section>
  );
}

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

function statusSubtext(
  status: RecordingStatus,
  streamingAnswer: string,
  lastResult: PipelineResult | null,
) {
  switch (status) {
    case "recording":
      return "I'm listening...";
    case "requesting":
      return "Requesting mic access";
    case "error":
      return "Check your microphone permissions";
    default:
      // While a conversation answer is still streaming in, show it live;
      // once "done" arrives, lastResult.answer is the final text
      // (identical content, but stable rather than growing).
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
        "transition-colors duration-150 ease-in-out cursor-pointer",
        isActive
          ? "bg-primary pulse"
          : "hover:bg-primary/50 border-2 border-primary bg-primary/60",
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
        className="text-white/95 relative z-50"
      />
      {Array.from({ length: 4 }, (_, i) => (
        <span key={i} style={{ "--i": i } as React.CSSProperties} />
      ))}
    </button>
  );
}
