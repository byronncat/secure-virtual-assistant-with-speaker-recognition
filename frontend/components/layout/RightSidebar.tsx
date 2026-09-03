"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import clsx from "clsx";
import { AlertTriangle, Undo2 } from "lucide-react";
import { sendChatMessage, ApiError, type PipelineResult } from "@/lib/api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  rejected?: boolean;
  command?: string | null;
}

const LANGUAGE_OPTIONS = [
  { code: "en", label: "English" },
  { code: "vi", label: "Tiếng Việt" },
];

let nextId = 0;
function newId() {
  nextId += 1;
  return `msg_${nextId}`;
}

export default function RightSidebar() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [language, setLanguage] = useState("en");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || isStreaming) return;

    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { id: newId(), role: "user", text }]);

    const assistantId = newId();
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", text: "" },
    ]);
    setIsStreaming(true);

    try {
      await sendChatMessage(text, language, {
        onAnswerChunk: (chunk) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, text: m.text + chunk } : m,
            ),
          );
        },
        onDone: (result: PipelineResult) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    text: result.answer || m.text,
                    rejected: result.rejected,
                    command: result.command,
                  }
                : m,
            ),
          );
        },
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Failed to reach the assistant.",
      );
      setMessages((prev) => prev.filter((m) => m.id !== assistantId));
    } finally {
      setIsStreaming(false);
    }
  }

  return (
    <aside className="flex size-full flex-col p-4">
      <div
        className={clsx(
          "flex flex-1 min-h-0 flex-col overflow-hidden",
          "rounded-xl border border-white/12 bg-card",
        )}
      >
        <div
          className={clsx(
            "flex items-center justify-between",
            "border-b border-white/12 px-4 py-3",
          )}
        >
          <span className="text-[16px] font-medium text-primary">Chat</span>
          <select
            aria-label="Response language"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className={clsx(
              "rounded-lg border border-white/12",
              "bg-background px-2 py-1",
              "text-[13px] text-normal",
              "outline-none cursor-pointer focus:border-primary",
            )}
          >
            {LANGUAGE_OPTIONS.map((opt) => (
              <option key={opt.code} value={opt.code}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3"
        >
          {messages.length === 0 && (
            <p className="text-[13px] text-muted">
              Type a message below to chat, or use the mic to run voice
              commands.
            </p>
          )}
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
        </div>

        {error && (
          <p role="alert" className="px-4 pb-2 text-[13px] text-red-400">
            {error}
          </p>
        )}

        <form
          onSubmit={handleSubmit}
          className="flex items-center gap-2 border-t border-white/12 p-3"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            disabled={isStreaming}
            className={clsx(
              "flex-1 rounded-lg border border-white/12 bg-background px-3 py-2",
              "text-[14px] text-normal outline-none focus:border-primary",
              "disabled:opacity-60",
            )}
          />
          <button
            type="submit"
            aria-label="Send message"
            disabled={isStreaming || !input.trim()}
            className={clsx(
              "flex size-9 items-center justify-center rounded-lg bg-primary text-background",
              "transition-opacity cursor-pointer",
              "hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            <Undo2 size={16} strokeWidth={1.75} />
          </button>
        </form>
      </div>
    </aside>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div
      className={clsx(
        "flex flex-col gap-1",
        isUser ? "items-end" : "items-start",
      )}
    >
      <div
        className={clsx(
          "max-w-[85%] rounded-xl px-3 py-2 text-[14px]",
          isUser ? "bg-primary text-background" : "bg-white/8 text-normal",
        )}
      >
        {message.text || (message.role === "assistant" ? "..." : "")}
      </div>
      {message.rejected && (
        <span className="flex items-center gap-1 text-[12px] text-red-400">
          <AlertTriangle size={12} strokeWidth={2} />
          Command &ldquo;{message.command}&rdquo; was rejected
        </span>
      )}
    </div>
  );
}
