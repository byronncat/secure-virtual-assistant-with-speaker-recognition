"use client";

import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, Loader2, Mic, Trash2, XCircle } from "lucide-react";
import {
  addEnrollmentSample,
  deleteEnrollmentSample,
  fetchEnrollmentStatus,
  ApiError,
  type EnrollmentStatus,
} from "@/lib/api";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";

type SlotState =
  | "recorded"
  | "recording"
  | "processing"
  | "failed"
  | "deleting";

interface EnrollmentPanelProps {
  /** "wizard": first-time registration flow, calls onComplete once the
   * centroid is ready. "manage": ongoing management, no completion step. */
  mode: "wizard" | "manage";
  onComplete?: () => void;
}

export default function EnrollmentPanel({
  mode,
  onComplete,
}: EnrollmentPanelProps) {
  const [enrollmentStatus, setEnrollmentStatus] =
    useState<EnrollmentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Transient per-action state, keyed by sample index for deletes, or the
  // literal "new" for an in-progress recording
  // (recording / processing / failed) live only here since the backend
  // only tracks what's actually been saved.
  const [pendingStates, setPendingStates] = useState<Record<string, SlotState>>(
    {},
  );

  useEffect(() => {
    let ignore = false;
    async function init() {
      try {
        const status = await fetchEnrollmentStatus();
        if (!ignore) {
          setEnrollmentStatus(status);
          setError(null);
          if (mode === "wizard" && status.centroid_ready) {
            onComplete?.();
          }
        }
      } catch (err) {
        if (!ignore) {
          setError(
            err instanceof ApiError
              ? err.message
              : "Could not load enrollment status.",
          );
        }
      }
    }
    init();
    return () => {
      ignore = true;
    };
  }, [mode, onComplete]);

  const { status: recorderStatus, start, stop } = useVoiceRecorder();

  const handleRecordNew = useCallback(async () => {
    setPendingStates((s) => ({ ...s, new: "recording" }));
    await start();
  }, [start]);

  const handleStopRecording = useCallback(async () => {
    const result = stop();
    if (!result) {
      setPendingStates((s) => ({ ...s, new: "failed" }));
      return;
    }
    setPendingStates((s) => ({ ...s, new: "processing" }));
    try {
      const status = await addEnrollmentSample(result.pcm, result.sampleRate);
      setEnrollmentStatus(status);
      setPendingStates((s) => {
        const next = { ...s };
        delete next.new;
        return next;
      });
      if (mode === "wizard" && status.centroid_ready) {
        onComplete?.();
      }
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to save recording.",
      );
      setPendingStates((s) => ({ ...s, new: "failed" }));
    }
  }, [stop, mode, onComplete]);

  const handleDelete = useCallback(async (index: number) => {
    setPendingStates((s) => ({ ...s, [index]: "deleting" }));
    try {
      const status = await deleteEnrollmentSample(index);
      setEnrollmentStatus(status);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to delete sample.",
      );
    } finally {
      setPendingStates((s) => {
        const next = { ...s };
        delete next[index];
        return next;
      });
    }
  }, []);

  if (!enrollmentStatus) {
    return (
      <div
        className={clsx(
          "flex items-center gap-2",
          "p-6 text-[14px] text-muted",
        )}
      >
        <Loader2 size={16} className="animate-spin" /> Loading enrollment
        status...
      </div>
    );
  }

  const { samples, sample_count, required_samples, centroid_ready } =
    enrollmentStatus;
  const isRecordingNew = pendingStates.new === "recording";
  const isBusy =
    recorderStatus === "requesting" || recorderStatus === "processing";

  return (
    <div className="flex flex-col p-6">
      <div>
        <h2 className="text-[20px] font-semibold">Voice Enrollment</h2>
        <p className="text-[13px] text-muted">
          {mode === "wizard"
            ? `Record ${required_samples} short voice samples so we can verify it's you for important commands.`
            : "Manage your enrolled voice samples."}
        </p>
      </div>

      <div className="flex flex-col gap-2 mt-5">
        {samples.map((sample) => (
          <SampleRow
            key={sample.index}
            label={`Sample ${sample.index}`}
            state={
              (pendingStates[sample.index] as SlotState | undefined) ??
              "recorded"
            }
            onDelete={() => handleDelete(sample.index)}
          />
        ))}

        {isRecordingNew ||
        pendingStates.new === "processing" ||
        pendingStates.new === "failed" ? (
          <SampleRow
            label={`Sample ${sample_count + 1}`}
            state={pendingStates.new as SlotState}
          />
        ) : null}

        {samples.length === 0 && !isRecordingNew && (
          <p className="text-[13px] text-muted">No samples recorded yet.</p>
        )}
      </div>

      <div className="mt-5">
        {error && (
          <p role="alert" className="text-[13px] text-red-400 mb-3">
            {error}
          </p>
        )}

        <div className="flex items-center gap-3">
          {!isRecordingNew ? (
            <button
              type="button"
              disabled={isBusy}
              onClick={handleRecordNew}
              className={clsx(
                "flex items-center gap-2",
                "rounded-xl border border-primary",
                "px-4 py-2.5",
                "text-[14px] font-medium text-primary",
                "transition-colors hover:bg-primary hover:text-background",
                "disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer",
              )}
            >
              <Mic size={16} strokeWidth={1.75} />
              Record Sample
            </button>
          ) : (
            <button
              type="button"
              onClick={handleStopRecording}
              className={clsx(
                "flex items-center gap-2",
                "rounded-xl bg-primary px-4 py-2.5",
                "text-[14px] font-medium text-background",
                "transition-opacity hover:opacity-80 cursor-pointer",
              )}
            >
              <Mic size={16} strokeWidth={1.75} className="pulse" />
              Stop &amp; Save
            </button>
          )}
        </div>
      </div>

      <div
        className={clsx(
          "flex items-center gap-2",
          "rounded-lg border",
          "px-3 py-2 mt-3 text-[12px]",
          centroid_ready
            ? "border-green-300/40 text-green-400"
            : "border-white/12 text-muted",
        )}
      >
        {centroid_ready ? (
          <CheckCircle2 size={16} strokeWidth={1.75} />
        ) : (
          <XCircle size={16} strokeWidth={1.75} />
        )}
        Centroid:{" "}
        {centroid_ready
          ? "Up to date"
          : `Needs ${required_samples} samples (have ${sample_count})`}
      </div>
    </div>
  );
}

interface SampleRowProps {
  label: string;
  state: SlotState;
  onDelete?: () => void;
}

function SampleRow({ label, state, onDelete }: SampleRowProps) {
  return (
    <div
      className={clsx(
        "flex items-center justify-between",
        "rounded-lg border border-white/12",
        "px-3 py-2.5",
      )}
    >
      <span className="text-[14px] text-normal">{label}</span>
      <div className="flex items-center gap-3">
        <StateBadge state={state} />
        {state === "recorded" && onDelete && (
          <button
            type="button"
            aria-label={`Delete ${label}`}
            onClick={onDelete}
            className="text-muted transition-colors hover:text-red-400 cursor-pointer"
          >
            <Trash2 size={16} strokeWidth={1.75} />
          </button>
        )}
      </div>
    </div>
  );
}

function StateBadge({ state }: { state: SlotState }) {
  switch (state) {
    case "recorded":
      return (
        <span className="flex items-center gap-1 text-[13px] text-green-400">
          <CheckCircle2 size={14} strokeWidth={1.75} /> Recorded
        </span>
      );
    case "recording":
      return (
        <span className="flex items-center gap-1 text-[13px] text-red-400">
          <Mic size={14} strokeWidth={1.75} className="pulse" /> Recording...
        </span>
      );
    case "processing":
      return (
        <span className="flex items-center gap-1 text-[13px] text-muted">
          <Loader2 size={14} strokeWidth={1.75} className="animate-spin" />{" "}
          Processing...
        </span>
      );
    case "deleting":
      return (
        <span className="flex items-center gap-1 text-[13px] text-muted">
          <Loader2 size={14} strokeWidth={1.75} className="animate-spin" />{" "}
          Deleting...
        </span>
      );
    case "failed":
      return (
        <span className="flex items-center gap-1 text-[13px] text-red-400">
          <XCircle size={14} strokeWidth={1.75} /> Failed, try again
        </span>
      );
    default:
      return null;
  }
}
