"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  fetchCurrentUser,
  getStoredToken,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  setStoredToken,
  type UserPublic,
} from "./api";

interface AuthContextValue {
  user: UserPublic | null;
  /** true while the initial /api/auth/me check (session restore) is running */
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (
    username: string,
    name: string,
    password: string,
  ) => Promise<UserPublic>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Restore session on load: a token in localStorage alone isn't trusted
  // -- it's validated against the backend so an expired/revoked token
  // doesn't leave the UI in a false "logged in" state.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getStoredToken()) {
        setIsLoading(false);
        return;
      }
      try {
        const me = await fetchCurrentUser();
        if (!cancelled) setUser(me);
      } catch {
        setStoredToken(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    setStoredToken(res.access_token);
    setUser(res.user);
  }, []);

  const register = useCallback(
    async (username: string, name: string, password: string) => {
      const res = await apiRegister(username, name, password);
      setStoredToken(res.access_token);
      setUser(res.user);
      return res.user;
    },
    [],
  );

  const logout = useCallback(async () => {
    await apiLogout();
    setStoredToken(null);
    setUser(null);
  }, []);

  const refreshUser = useCallback(async () => {
    const me = await fetchCurrentUser();
    setUser(me);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, isLoading, login, register, logout, refreshUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
