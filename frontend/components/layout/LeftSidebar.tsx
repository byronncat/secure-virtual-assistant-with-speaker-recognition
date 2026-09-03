"use client";

import {
  ChevronDown,
  Loader2,
  LogOut,
  Plus,
  RefreshCw,
  Settings,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import CommandItem from "../commands/CommandItem";
import clsx from "clsx";
import { useAuth } from "@/lib/auth-context";
import SettingsModal from "../SettingsModel";
import { ApiError, fetchCommands, type CommandDefinition } from "@/lib/api";

export default function LeftSidebar() {
  const [settingsTab, setSettingsTab] = useState<
    "enrollment" | "commands" | null
  >(null);
  const [commands, setCommands] = useState<CommandDefinition[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuth();

  const loadCommands = useCallback(async () => {
    try {
      setIsLoading(true);
      const data = await fetchCommands();
      setCommands(data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to load commands.",
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCommands();
  }, [loadCommands, user]);

  const handleCloseSettings = () => {
    setSettingsTab(null);
    // Reload commands in case any were added, edited, or deleted in the modal
    loadCommands();
  };

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
        <CommandList
          commands={commands}
          isLoading={isLoading}
          error={error}
          onRetry={loadCommands}
        />
        <AddCommandButton onClick={() => setSettingsTab("commands")} />
        <Footer onOpenSettings={() => setSettingsTab("enrollment")} />
      </div>

      {settingsTab && (
        <SettingsModal initialTab={settingsTab} onClose={handleCloseSettings} />
      )}
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

interface CommandListProps {
  commands: CommandDefinition[] | null;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

function CommandList({
  commands,
  isLoading,
  error,
  onRetry,
}: CommandListProps) {
  return (
    <div className="flex-1 overflow-y-auto flex flex-col min-h-0">
      <div
        className={clsx(
          "px-4 py-3 bg-white/5",
          "flex items-center justify-between",
          "border-b border-white/12",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="font-medium text-[15px] text-primary">Commands</span>
          {commands && commands.length > 0 && (
            <span
              className={clsx(
                "flex items-center justify-center",
                "size-6 rounded-full bg-primary/15",
                "text-[12px] text-primary font-medium",
              )}
            >
              {commands.length}
            </span>
          )}
        </div>
      </div>

      <div className="h-full flex flex-col overflow-auto gap-0.5">
        {isLoading && (!commands || commands.length === 0) ? (
          <div className="flex flex-col items-center justify-center p-8 gap-2 text-muted">
            <Loader2 size={20} className="animate-spin text-muted" />
            <span className="text-[13px]">Loading commands...</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center p-6 gap-2 text-center">
            <p className="text-[14px] text-red-400">{error}</p>
            <button
              type="button"
              onClick={onRetry}
              className={clsx(
                "flex items-center gap-1.5",
                "text-[12px] text-muted cursor-pointer",
                "hover:opacity-80 transition-opacity ease-in-out",
              )}
            >
              <RefreshCw size={16} /> Retry
            </button>
          </div>
        ) : !commands || commands.length === 0 ? (
          <div className="flex flex-col items-center justify-center p-8 text-center text-muted">
            <p className="text-[13px]">No commands registered.</p>
            <p className="text-[11.5px] text-muted/70 mt-1">
              Click &ldquo;Add Command&rdquo; below to create one.
            </p>
          </div>
        ) : (
          commands.map((command) => (
            <CommandItem key={command.id || command.intent} command={command} />
          ))
        )}
      </div>
    </div>
  );
}

function AddCommandButton({ onClick }: { onClick: () => void }) {
  return (
    <div className="px-3 pt-3">
      <button
        type="button"
        onClick={onClick}
        className={clsx(
          "flex w-full items-center justify-center gap-2",
          "rounded-xl border border-primary",
          "py-2.5 text-[14px] font-medium text-primary",
          "transition-colors ease-in-out cursor-pointer",
          "hover:bg-primary hover:text-background",
        )}
      >
        <Plus size={16} strokeWidth={2} />
        Add Command
      </button>
    </div>
  );
}

function Footer({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const initials = (user?.name ?? "?").slice(0, 2).toUpperCase();

  return (
    <div
      className={clsx(
        "relative mt-4 border-t border-white/12",
        "py-3 px-2",
        "flex items-center justify-between gap-1",
      )}
    >
      <button
        type="button"
        onClick={() => setMenuOpen((open) => !open)}
        className={clsx(
          "flex w-full items-center gap-2.5",
          "rounded-xl px-2 py-2",
          "transition-colors ease-in-out",
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
          {initials}
        </span>
        <span className="flex-1 text-left text-[14px] text-normal font-medium">
          {user?.name ?? "Guest"}
        </span>
        <ChevronDown size={14} className="text-normal" />
      </button>
      <button
        type="button"
        onClick={onOpenSettings}
        className={clsx(
          "w-9 flex items-center justify-center",
          "rounded-lg p-2 text-muted",
          "transition-colors hover:bg-white/10 hover:text-normal cursor-pointer",
        )}
        aria-label="Settings"
      >
        <Settings size={18} strokeWidth={1.75} />
      </button>

      {menuOpen && (
        <div
          className={clsx(
            "absolute bottom-16 left-2 z-10 w-[calc(100%-1rem)]",
            "rounded-xl border border-white/12 bg-card shadow-lg",
            "overflow-hidden",
          )}
        >
          <button
            type="button"
            onClick={() => {
              setMenuOpen(false);
              logout();
            }}
            className={clsx(
              "flex w-full items-center gap-2",
              "px-3 py-2.5 text-left",
              "text-[14px] text-red-400",
              "hover:bg-white/10 cursor-pointer",
            )}
          >
            <LogOut size={15} strokeWidth={1.75} />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
