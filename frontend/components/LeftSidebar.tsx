import {
  FileText,
  Bell,
  CloudSun,
  Search,
  Mail,
  Calendar,
  Music2,
  Activity,
  Plus,
  Settings,
  ChevronDown,
} from "lucide-react";
import CommandItem from "./CommandItem";
import type { VoiceCommand } from "./types";
import clsx from "clsx";

const COMMANDS: VoiceCommand[] = [
  {
    id: "notes",
    label: "Open Notes",
    description: "Open my notes",
    icon: FileText,
    important: true,
  },
  {
    id: "reminder",
    label: "Set Reminder",
    description: "Set a reminder for me",
    icon: Bell,
    important: true,
  },
  {
    id: "weather",
    label: "Weather",
    description: "Check the weather",
    icon: CloudSun,
    important: false,
  },
  {
    id: "search",
    label: "Search Web",
    description: "Search the web",
    icon: Search,
    important: false,
  },
  {
    id: "email",
    label: "Send Email",
    description: "Send an email",
    icon: Mail,
    important: true,
  },
  {
    id: "calendar",
    label: "Calendar",
    description: "Open my calendar",
    icon: Calendar,
    important: true,
  },
  {
    id: "music",
    label: "Play Music",
    description: "Play music",
    icon: Music2,
    important: false,
  },
  {
    id: "status",
    label: "System Status",
    description: "Check system status",
    icon: Activity,
    important: false,
  },
];

export default function LeftSidebar() {
  return (
    <aside
      className={clsx(
        "size-full flex flex-col",
        "min-h-0", // Command list should be scrollable
      )}
    >
      <Logo />
      <div
        className={clsx(
          "flex-1 bg-card",
          "flex flex-col",
          "mx-4 mb-4",
          "rounded-xl border border-white/12 overflow-hidden",
          "min-h-0", // Command list should be scrollable
        )}
      >
        <CommandList />
        <AddCommandButton />
        <Footer />
      </div>
    </aside>
  );
}

function Logo() {
  return (
    <div className={clsx("px-6 pb-6 pt-7", "text-[24px]")}>
      Voice<span className="font-semibold text-primary ml-2">Assistant</span>
    </div>
  );
}

function CommandList() {
  return (
    <div className="flex-1 overflow-y-auto flex flex-col">
      <p
        className={clsx(
          "px-4 py-3 text-[16px] bg-white/5",
          "font-medium text-primary",
          "border-b border-white/12",
        )}
      >
        Commands
      </p>
      <div className="flex flex-col overflow-auto h-full">
        {COMMANDS.map((command) => (
          <CommandItem key={command.id} command={command} />
        ))}
      </div>
    </div>
  );
}

function AddCommandButton() {
  return (
    <div className="px-3 pt-3">
      <button
        type="button"
        className={clsx(
          "flex w-full items-center justify-center gap-2",
          "rounded-xl border border-primary",
          "py-2.5 text-[14px] font-medium text-primary",
          "transition-colors ease-in-out duration-200 cursor-pointer",
          "hover:bg-primary hover:text-background",
        )}
      >
        <Plus size={16} strokeWidth={2} />
        Add Command
      </button>
    </div>
  );
}

function Footer() {
  return (
    <div
      className={clsx(
        "mt-4 border-t border-white/12",
        "py-3 px-2",
        "flex items-center justify-between gap-1",
      )}
    >
      <button
        type="button"
        className={clsx(
          "flex w-full items-center gap-2.5",
          "rounded-xl px-2 py-2",
          "transition-colors ease-in-out duration-200",
          "hover:bg-white/10 cursor-pointer",
        )}
      >
        <span
          className={clsx(
            "flex size-8 shrink-0 items-center justify-center",
            "rounded-full bg-background",
            "text-[12px] font-semibold text-normal",
          )}
        >
          By
        </span>
        <span className="flex-1 text-left text-[14px] text-normal font-medium">
          Byron
        </span>
        <ChevronDown size={14} className="text-normal" />
      </button>
      <button
        type="button"
        className={clsx(
          "w-9 flex items-center justify-center",
          "rounded-lg p-2 text-muted",
          "transition-colors hover:bg-white/10 hover:text-normal cursor-pointer",
        )}
        aria-label="Settings"
      >
        <Settings size={18} strokeWidth={1.75} />
      </button>
    </div>
  );
}
