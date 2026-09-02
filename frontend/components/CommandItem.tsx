import type { VoiceCommand } from "./types";
import clsx from "clsx";
import { getLucideIcon } from "@/lib/icons";

interface CommandItemProps {
  command: VoiceCommand;
}

export default function CommandItem({ command }: CommandItemProps) {
  const Icon =
    typeof command.icon === "string"
      ? getLucideIcon(command.icon)
      : command.icon;

  return (
    <button
      type="button"
      className={clsx(
        "group",
        "flex w-full items-center gap-3",
        "px-3 py-2.5 text-left",
        "transition-colors ease-in-out",
        "text-muted hover:text-normal hover:bg-white/5 cursor-pointer",
      )}
    >
      <span
        className={clsx(
          "size-9 flex shrink-0 items-center justify-center",
          "rounded-lg border border-white/20",
          "bg-background transition-colors",
        )}
      >
        <Icon size={16} strokeWidth={1.75} />
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="block truncate text-[14px] font-medium text-ink">
            {command.label}
          </span>
          {command.important && (
            <span className="rounded-full bg-red-400 size-1.5" />
          )}
        </div>
        <span className="block truncate text-[12.5px]">
          {command.description}
        </span>
      </div>
    </button>
  );
}
