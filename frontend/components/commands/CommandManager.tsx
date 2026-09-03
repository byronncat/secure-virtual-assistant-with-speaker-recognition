"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";
import { Loader2, Pencil, Plus, ShieldCheck, Trash2 } from "lucide-react";
import {
  ApiError,
  createCommand,
  deleteCommand,
  fetchCommands,
  updateCommand,
  type CommandDefinition,
} from "@/lib/api";
import { getLucideIcon } from "@/lib/icons";
import CommandForm from "./CommandForm";

export default function CommandManager() {
  const [commands, setCommands] = useState<CommandDefinition[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [editingIntent, setEditingIntent] = useState<string | null>(null);

  async function reload() {
    try {
      setCommands(await fetchCommands());
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load commands.",
      );
    }
  }

  useEffect(() => {
    let ignore = false;
    async function init() {
      try {
        const list = await fetchCommands();
        if (!ignore) {
          setCommands(list);
          setError(null);
        }
      } catch (err) {
        if (!ignore) {
          setError(
            err instanceof ApiError ? err.message : "Could not load commands.",
          );
        }
      }
    }
    init();
    return () => {
      ignore = true;
    };
  }, []);

  async function handleDelete(intent: string) {
    try {
      await deleteCommand(intent);
      await reload();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not delete command.",
      );
    }
  }

  return (
    <div className="flex flex-col p-6">
      <div className="flex flex-col items-start gap-3">
        <div>
          <h2 className="text-[20px] font-semibold">Commands</h2>
          <p className="text-[13px] text-muted">
            Registered voice commands. Important commands require speaker
            verification before they run.
          </p>
        </div>
        {!isCreating && (
          <button
            type="button"
            onClick={() => setIsCreating(true)}
            className={clsx(
              "self-end",
              "flex items-center gap-1.5",
              "rounded-lg border border-primary px-3 py-1.5",
              "text-[13px] font-medium text-primary",
              "transition-colors hover:bg-primary hover:text-background cursor-pointer",
            )}
          >
            <Plus size={14} strokeWidth={2} /> New Command
          </button>
        )}
      </div>

      <div className="mt-3 space-y-3">
        {error && (
          <p role="alert" className="text-[13px] text-red-400">
            {error}
          </p>
        )}

        {isCreating && (
          <CommandForm
            onCancel={() => setIsCreating(false)}
            onSubmit={async (values) => {
              try {
                await createCommand(
                  values.intent,
                  values.label,
                  values.icon,
                  values.description,
                  values.important,
                );
                setIsCreating(false);
                await reload();
              } catch (err) {
                setError(
                  err instanceof ApiError
                    ? err.message
                    : "Could not create command.",
                );
              }
            }}
          />
        )}

        {commands === null ? (
          <div className="flex items-center gap-2 text-[14px] text-muted py-6">
            <Loader2 size={16} className="animate-spin text-muted" /> Loading
            commands...
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {commands.map((command) => {
              const Icon = getLucideIcon(command.icon);
              return editingIntent === command.intent ? (
                <CommandForm
                  key={command.intent}
                  initial={command}
                  onCancel={() => setEditingIntent(null)}
                  onSubmit={async (values) => {
                    try {
                      await updateCommand(command.intent, {
                        label: values.label,
                        icon: values.icon,
                        description: values.description,
                        important: values.important,
                      });
                      setEditingIntent(null);
                      await reload();
                    } catch (err) {
                      setError(
                        err instanceof ApiError
                          ? err.message
                          : "Could not update command.",
                      );
                    }
                  }}
                />
              ) : (
                <div
                  key={command.intent}
                  className={clsx(
                    "flex items-center justify-between rounded-xl border border-white/12 bg-white/5 p-3",
                    "transition-colors hover:border-white/20",
                  )}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span
                      className={clsx(
                        "size-10 flex shrink-0 items-center justify-center",
                        "rounded-lg border border-white/20 bg-background text-normal",
                      )}
                    >
                      <Icon size={18} strokeWidth={1.75} />
                    </span>
                    <div className="flex flex-col gap-0.5 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[14.5px] font-medium text-normal">
                          {command.label || command.intent}
                        </span>
                        <span className="font-mono text-[11px] text-muted/80 bg-background/80 px-1.5 py-0.5 rounded border border-white/8">
                          {command.intent}
                        </span>
                        {command.important && (
                          <span className="flex items-center gap-1 rounded-full bg-red-400/15 px-2 py-0.5 text-[11px] font-medium text-red-400">
                            <ShieldCheck size={11} strokeWidth={2} /> important
                          </span>
                        )}
                      </div>
                      <span className="text-[12.5px] text-muted truncate">
                        {command.description}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    <button
                      type="button"
                      aria-label={`Edit ${command.intent}`}
                      onClick={() => setEditingIntent(command.intent)}
                      className="p-1.5 text-muted transition-colors hover:text-normal cursor-pointer"
                    >
                      <Pencil size={15} strokeWidth={1.75} />
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete ${command.intent}`}
                      onClick={() => handleDelete(command.intent)}
                      className="p-1.5 text-muted transition-colors hover:text-red-400 cursor-pointer"
                    >
                      <Trash2 size={15} strokeWidth={1.75} />
                    </button>
                  </div>
                </div>
              );
            })}
            {commands.length === 0 && (
              <p className="text-[13px] text-muted py-4 text-center">
                No commands registered yet.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
