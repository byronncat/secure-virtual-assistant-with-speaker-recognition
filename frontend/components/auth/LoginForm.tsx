"use client";

import { useState, type SubmitEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import clsx from "clsx";
import LabeledInput from "./LabeledInput";
import { Lock, User } from "lucide-react";

interface LoginFormProps {
  onSwitchToRegister: () => void;
}

export default function LoginForm({ onSwitchToRegister }: LoginFormProps) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not reach the server. Please try again.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="size-full flex items-center justify-center">
      <form
        onSubmit={handleSubmit}
        className={clsx(
          "w-full max-w-[380px]",
          "rounded-xl border border-white/12 bg-card",
          "flex flex-col p-8",
        )}
      >
        <div className="flex flex-col gap-1">
          <h1 className="text-[24px] font-semibold">Welcome back</h1>
          <p className="text-[14px] text-muted">
            Log in to your Voice Assistant account.
          </p>
        </div>

        <div className="mt-5 space-y-3">
          <LabeledInput
            icon={<User size={16} strokeWidth={1.75} />}
            label="Username"
            type="text"
            value={username}
            onChange={setUsername}
            placeholder="e.g. alice"
            autoComplete="username"
            required
          />
          <LabeledInput
            icon={<Lock size={16} strokeWidth={1.75} />}
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
            required
          />
        </div>

        <div className="mt-5 w-full">
          {error && (
            <p role="alert" className="text-[13px] text-red-400 mb-3">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className={clsx(
              "w-full rounded-xl bg-primary py-2.5",
              "text-[14px] font-medium text-background",
              "transition-opacity duration-150 hover:opacity-80 cursor-pointer",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
          >
            {isSubmitting ? "Logging in..." : "Log In"}
          </button>
        </div>

        <p className="text-center text-[14px] text-muted mt-3">
          Don&apos;t have an account?{" "}
          <button
            type="button"
            onClick={onSwitchToRegister}
            className="font-medium text-primary hover:underline cursor-pointer"
          >
            Register
          </button>
        </p>
      </form>
    </div>
  );
}
