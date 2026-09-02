"use client";

import { useState } from "react";
import clsx from "clsx";
import { X } from "lucide-react";
import EnrollmentPanel from "./EnrollmentPanel";
import CommandManager from "./CommandManager";

type Tab = "enrollment" | "commands";

interface SettingsModalProps {
  onClose: () => void;
  initialTab?: Tab;
}

export default function SettingsModal({
  onClose,
  initialTab = "enrollment",
}: SettingsModalProps) {
  const [tab, setTab] = useState<Tab>(initialTab);

  return (
    <div
      className={clsx(
        "fixed inset-0 z-50",
        "bg-black/60 p-6",
        "flex items-center justify-center",
      )}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={clsx(
          "flex flex-col max-h-[85vh] w-full max-w-[560px] overflow-hidden",
          "rounded-xl border border-white/12 bg-card",
        )}
      >
        <div
          className={clsx(
            "flex items-center justify-between",
            "border-b border-white/12 px-4 py-3",
          )}
        >
          <div className="flex gap-1">
            <TabButton
              active={tab === "enrollment"}
              onClick={() => setTab("enrollment")}
            >
              Voice Enrollment
            </TabButton>
            <TabButton
              active={tab === "commands"}
              onClick={() => setTab("commands")}
            >
              Commands
            </TabButton>
          </div>
          <button
            type="button"
            aria-label="Close settings"
            onClick={onClose}
            className="text-muted transition-colors hover:text-normal cursor-pointer"
          >
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>

        <div className="overflow-y-auto">
          {tab === "enrollment" ? (
            <EnrollmentPanel mode="manage" />
          ) : (
            <CommandManager />
          )}
        </div>
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        "rounded-lg px-3 py-1.5",
        "text-[14px] font-medium",
        "transition-colors cursor-pointer",
        active ? "bg-primary text-background" : "text-muted hover:text-normal",
      )}
    >
      {children}
    </button>
  );
}
