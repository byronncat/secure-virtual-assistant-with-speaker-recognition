"use client";

import { useState, type SubmitEvent } from "react";
import clsx from "clsx";
import { Contact, Lock, User } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { ApiError, type UserPublic } from "@/lib/api";
import LabeledInput from "./LabeledInput";

interface RegisterFormProps {
  onSwitchToLogin: () => void;
  /** Called once the account is created, so the parent can move on to
   * the voice-enrollment wizard (registration doesn't collect voice
   * samples itself). */
  onRegistered: (user: UserPublic) => void;
}

export default function RegisterForm({
  onSwitchToLogin,
  onRegistered,
}: RegisterFormProps) {
  const { register } = useAuth();
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    setIsSubmitting(true);
    try {
      const user = await register(username.trim(), name.trim(), password);
      onRegistered(user);
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
    <div className="flex size-full items-center justify-center">
      <form
        onSubmit={handleSubmit}
        className={clsx(
          "w-full max-w-[380px]",
          "rounded-xl border border-white/12 bg-card",
          "flex flex-col p-8",
        )}
      >
        <div className="flex flex-col gap-1">
          <h1 className="text-[24px] font-semibold">Create your account</h1>
        </div>

        <div className="mt-5 space-y-3">
          <LabeledInput
            icon={<User size={16} strokeWidth={1.75} />}
            label="Username"
            type="text"
            value={username}
            onChange={setUsername}
            placeholder="e.g. john"
            autoComplete="username"
            required
          />
          <LabeledInput
            icon={<Contact size={16} strokeWidth={1.75} />}
            label="Display name"
            type="text"
            value={name}
            onChange={setName}
            placeholder="e.g. John Smith"
            autoComplete="name"
            required
          />
          <LabeledInput
            icon={<Lock size={16} strokeWidth={1.75} />}
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            required
          />
          <LabeledInput
            icon={<Lock size={16} strokeWidth={1.75} />}
            label="Confirm password"
            type="password"
            value={confirmPassword}
            onChange={setConfirmPassword}
            autoComplete="new-password"
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
            {isSubmitting
              ? "Creating account..."
              : "Continue to Voice Enrollment"}
          </button>
        </div>

        <p className="text-center text-[14px] text-muted mt-3">
          Already have an account?{" "}
          <button
            type="button"
            onClick={onSwitchToLogin}
            className="font-medium text-primary hover:underline cursor-pointer"
          >
            Log in
          </button>
        </p>
      </form>
    </div>
  );
}
