"use client";

import { useState } from "react";
import clsx from "clsx";
import { Mic } from "lucide-react";
import ControlBar from "./ControlBar";

export default function CenterPanel() {
  return (
    <section
      className={clsx(
        "relative flex size-full flex-col items-center justify-between",
        "px-8 py-10",
      )}
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-10">
        <MicButton />

        <div
          className={clsx(
            "flex flex-col items-center",
            "gap-2 text-center",
            "relative z-10",
          )}
        >
          <h1 className="text-[30px] font-semibold">Tap to Speak</h1>
          <p className="text-[16px] text-faint">I&apos;m listening...</p>
        </div>
      </div>

      <ControlBar />
    </section>
  );
}

function MicButton() {
  const [isActive, setIsActive] = useState(false);

  return (
    <button
      type="button"
      aria-label="Mic button"
      className={clsx(
        "relative size-50 rounded-full",
        "flex items-center justify-center",
        "transition-colors duration-150 ease-in-out cursor-pointer",
        isActive
          ? "bg-primary pulse"
          : "hover:bg-primary/50 border-2 border-primary bg-primary/60",
      )}
      onPointerDown={() => setIsActive(true)}
      onPointerUp={() => setIsActive(false)}
      onPointerLeave={() => setIsActive(false)}
    >
      <Mic
        size={60}
        strokeWidth={1.5}
        className="text-white/95 relative z-50"
      />
      {Array.from({ length: 4 }, (_, i) => (
        <span key={i} style={{ "--i": i } as React.CSSProperties} />
      ))}
    </button>
  );
}
