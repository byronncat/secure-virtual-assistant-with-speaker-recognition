import { useState, type SubmitEvent } from "react";
import clsx from "clsx";
import { X } from "lucide-react";
import type { CommandDefinition } from "@/lib/api";
import { getLucideIcon, POPULAR_COMMAND_ICONS } from "@/lib/icons";

interface CommandFormValues {
  intent: string;
  label: string;
  icon: string;
  description: string;
  important: boolean;
}

interface CommandFormProps {
  initial?: CommandDefinition;
  onCancel: () => void;
  onSubmit: (values: CommandFormValues) => Promise<void>;
}

export default function CommandForm({
  initial,
  onCancel,
  onSubmit,
}: CommandFormProps) {
  const [intent, setIntent] = useState(initial?.intent ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [icon, setIcon] = useState(initial?.icon ?? "Terminal");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [important, setImportant] = useState(initial?.important ?? false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showIconPicker, setShowIconPicker] = useState(false);

  const PreviewIcon = getLucideIcon(icon);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await onSubmit({
        intent,
        label: label.trim() || intent,
        icon: icon.trim() || "Terminal",
        description,
        important,
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-3.5 rounded-xl border border-primary/40 bg-white/5 p-4"
    >
      <div className="flex items-center justify-between">
        <span className="text-[14px] font-medium text-primary">
          {initial ? `Edit ${initial.label || initial.intent}` : "New Command"}
        </span>
        <button
          type="button"
          onClick={onCancel}
          className="text-muted hover:text-normal cursor-pointer"
        >
          <X size={16} strokeWidth={1.75} />
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-[12px] font-medium text-muted">
            Label (UI Name)
          </label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Open Door"
            required
            className="rounded-lg border border-white/12 bg-background px-3 py-2 text-[14px] outline-none focus:border-primary"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[12px] font-medium text-muted">
            Intent {initial ? "(Immutable)" : "(snake_case identifier)"}
          </label>
          <input
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            disabled={!!initial}
            placeholder="e.g. open_door"
            required
            pattern="^[a-z][a-z0-9_]{1,63}$"
            title="Lowercase snake_case, e.g. open_door"
            className={clsx(
              "rounded-lg border border-white/12 bg-background px-3 py-2 text-[14px] outline-none focus:border-primary font-mono",
              initial && "opacity-60 cursor-not-allowed",
            )}
          />
        </div>
      </div>

      {/* Icon Selector */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label className="text-[12px] font-medium text-muted">
            Icon (Lucide React)
          </label>
          <button
            type="button"
            onClick={() => setShowIconPicker((prev) => !prev)}
            className="text-[11.5px] text-primary hover:underline cursor-pointer"
          >
            {showIconPicker ? "Hide Icon Grid" : "Choose from popular icons"}
          </button>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/20 bg-background text-normal">
            <PreviewIcon size={18} strokeWidth={1.75} />
          </div>
          <input
            value={icon}
            onChange={(e) => setIcon(e.target.value)}
            placeholder="Lucide icon name (e.g. Bell, DoorOpen, Terminal)"
            required
            className="flex-1 rounded-lg border border-white/12 bg-background px-3 py-2 text-[14px] outline-none focus:border-primary"
          />
        </div>

        {showIconPicker && (
          <div className="mt-1.5 max-h-40 overflow-y-auto rounded-lg border border-white/12 bg-background/90 p-2 grid grid-cols-4 sm:grid-cols-6 gap-1.5">
            {POPULAR_COMMAND_ICONS.map((opt) => {
              const ItemIcon = getLucideIcon(opt.name);
              const isSelected = icon.toLowerCase() === opt.name.toLowerCase();
              return (
                <button
                  key={opt.name}
                  type="button"
                  title={opt.label}
                  onClick={() => {
                    setIcon(opt.name);
                    setShowIconPicker(false);
                  }}
                  className={clsx(
                    "flex flex-col items-center justify-center gap-1 rounded-md p-2 text-center transition-colors cursor-pointer",
                    isSelected
                      ? "bg-primary text-background"
                      : "hover:bg-white/10 text-muted hover:text-normal",
                  )}
                >
                  <ItemIcon size={16} strokeWidth={1.75} />
                  <span className="text-[10.5px] truncate w-full">
                    {opt.name}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[12px] font-medium text-muted">
          Description
        </label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. Opens the front entrance door"
          required
          className="rounded-lg border border-white/12 bg-background px-3 py-2 text-[14px] outline-none focus:border-primary"
        />
      </div>

      <label className="flex items-center gap-2 text-[13px] text-muted cursor-pointer select-none">
        <input
          type="checkbox"
          checked={important}
          onChange={(e) => setImportant(e.target.checked)}
          className="size-4 accent-[var(--color-normal)] cursor-pointer"
        />
        Important (requires speaker verification before execution)
      </label>

      <div className="flex items-center justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className={clsx(
            "rounded-lg px-3 py-1.5",
            "text-[13px] text-muted hover:text-normal",
            "transition-colors cursor-pointer",
          )}
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className={clsx(
            "rounded-lg bg-primary px-4 py-1.5",
            "text-[13px] font-medium text-background",
            "transition-opacity hover:opacity-80 cursor-pointer",
            "disabled:cursor-not-allowed disabled:opacity-60",
          )}
        >
          {isSubmitting ? "Saving..." : "Save Command"}
        </button>
      </div>
    </form>
  );
}
