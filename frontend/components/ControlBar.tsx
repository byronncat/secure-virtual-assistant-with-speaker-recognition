import { Globe, Mic, ChevronDown } from "lucide-react";
import clsx from "clsx";

export default function ControlBar() {
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        className={clsx(
          "flex items-center gap-2",
          "rounded-full border border-white/24",
          "px-4 py-2.5 text-[12px] text-muted",
        )}
      >
        <Globe size={16} strokeWidth={1.75} />
        English (US)
        <ChevronDown size={14} />
      </button>

      <button
        type="button"
        className={clsx(
          "flex items-center gap-2",
          "rounded-full border border-white/24",
          "px-4 py-2.5 text-[12px] text-muted",
        )}
      >
        <Mic size={16} strokeWidth={1.75} />
        Mic: Default
        <ChevronDown size={14} />
      </button>
    </div>
  );
}
