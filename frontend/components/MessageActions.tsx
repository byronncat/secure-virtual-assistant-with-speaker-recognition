import clsx from "clsx";
import { Copy, ThumbsUp, ThumbsDown, Volume2 } from "lucide-react";

const ACTIONS = [
  { id: "copy", icon: Copy, label: "Copy response" },
  { id: "up", icon: ThumbsUp, label: "Good response" },
  { id: "down", icon: ThumbsDown, label: "Bad response" },
  { id: "listen", icon: Volume2, label: "Read aloud" },
];

export default function MessageActions() {
  return (
    <div className="flex items-center gap-2 -mt-2">
      {ACTIONS.map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          type="button"
          aria-label={label}
          className={clsx(
            "text-muted",
            "transition-colors ease-in-out duration-200 hover:bg-white/10 ",
            "p-1.5 rounded-md cursor-pointer",
          )}
        >
          <Icon size={16} strokeWidth={1.75} />
        </button>
      ))}
    </div>
  );
}
