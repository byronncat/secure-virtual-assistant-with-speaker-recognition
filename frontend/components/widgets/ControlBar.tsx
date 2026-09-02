"use client";

import clsx from "clsx";
import { Languages } from "lucide-react";

const LANGUAGE_OPTIONS = [
  { code: "en", label: "English" },
  { code: "vi", label: "Tiếng Việt" },
];

interface ControlBarProps {
  language: string;
  onLanguageChange: (language: string) => void;
}

export default function ControlBar({
  language,
  onLanguageChange,
}: ControlBarProps) {
  return (
    <div
      className={clsx(
        "flex items-center gap-2",
        "rounded-xl border border-white/12 bg-card",
        "px-3 py-2 text-[14px]",
      )}
    >
      <Languages size={15} strokeWidth={1.75} className="text-muted" />
      <select
        aria-label="Voice command language"
        value={language}
        onChange={(e) => onLanguageChange(e.target.value)}
        className="bg-transparent text-normal outline-none cursor-pointer"
      >
        {LANGUAGE_OPTIONS.map((opt) => (
          <option
            key={opt.code}
            value={opt.code}
            className="bg-card text-normal"
          >
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
