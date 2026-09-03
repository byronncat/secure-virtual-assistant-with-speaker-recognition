"use client";

import { useState } from "react";
import clsx from "clsx";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import { Loader2 } from "lucide-react";
import LeftSidebar from "@/components/layout/LeftSidebar";
import CenterPanel from "@/components/layout/CenterPanel";
import RightSidebar from "@/components/layout/RightSidebar";
import LoginForm from "@/components/auth/LoginForm";
import RegisterForm from "@/components/auth/RegisterForm";
import EnrollmentPanel from "@/components/EnrollmentPanel";

export default function Home() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}

type UnauthScreen = "login" | "register";

function AppShell() {
  const { user, isLoading } = useAuth();
  const [screen, setScreen] = useState<UnauthScreen>("login");
  // Once a fresh registration succeeds, `user` becomes non-null but the
  // account still has zero voice samples -- the enrollment wizard is
  // shown until the centroid is ready, rather than dropping
  // straight into the main app with an unusable voice identity.
  const [justRegistered, setJustRegistered] = useState(false);

  if (isLoading) {
    return (
      <main
        className={clsx(
          "h-screen bg-background",
          "flex flex-col items-center justify-center",
        )}
      >
        <Loader2 className="size-12 text-faint animate-spin" />
        <p className="text-[16px] text-faint mt-2 animate-pulse">Loading...</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className={clsx("h-screen", "flex items-center justify-center")}>
        {screen === "login" ? (
          <LoginForm onSwitchToRegister={() => setScreen("register")} />
        ) : (
          <RegisterForm
            onSwitchToLogin={() => setScreen("login")}
            onRegistered={() => setJustRegistered(true)}
          />
        )}
      </main>
    );
  }

  if (justRegistered) {
    return (
      <main
        className={clsx(
          "h-screen bg-background p-6",
          "flex items-center justify-center",
        )}
      >
        <div
          className={clsx(
            "w-full max-w-[480px] bg-card",
            "rounded-xl border border-white/12",
          )}
        >
          <EnrollmentPanel
            mode="wizard"
            onComplete={() => setJustRegistered(false)}
          />
        </div>
      </main>
    );
  }

  return (
    <main
      className={clsx(
        "grid h-screen grid-cols-[300px_1fr_380px]",
        "overflow-hidden bg-background text-normal",
      )}
    >
      <LeftSidebar />
      <CenterPanel />
      <RightSidebar />
    </main>
  );
}
