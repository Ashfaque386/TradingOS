"use client";

// Auth context (Phase 4 exit-criteria gap: RBAC; REL-007 added MFA + refresh-token rotation on
// the backend, see src/core/security.py's module docstring). Tokens live in localStorage, not
// the httpOnly Secure SameSite cookie Phase_12_Security_Design.md §2.1 specs -- confirmed with
// the user during REL-007 to keep this MVP simplification rather than build CSRF protection for
// a cookie-based session no other frontend code consumes yet. Real Next.js middleware-based
// route protection needs a cookie it can read at the edge; a localStorage token can only be
// checked client-side, which is what RequireAuth below does.

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setAuthToken, ROLES, type Role, type LoginResponse } from "@/lib/api";

interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  /** Raw login call, no side effects -- the caller (login page) inspects `mfa_required` and
   * either treats this as a completed login (calls completeSession itself) or drives the
   * enroll/verify UI first. */
  login: (email: string, password: string) => Promise<LoginResponse>;
  /** Persists a real access_token/refresh_token pair and loads the current user -- called
   * directly after a non-MFA login, or after /mfa/confirm or /mfa/verify succeeds. */
  completeSession: (accessToken: string, refreshToken: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY = "tradingos_access_token";
const REFRESH_STORAGE_KEY = "tradingos_refresh_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function restoreSession() {
      const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
      if (!stored) {
        setLoading(false);
        return;
      }
      setAuthToken(stored);
      try {
        setUser(await api.me());
      } catch {
        setAuthToken(null);
        localStorage.removeItem(STORAGE_KEY);
        localStorage.removeItem(REFRESH_STORAGE_KEY);
      } finally {
        setLoading(false);
      }
    }
    void restoreSession();
  }, []);

  async function login(email: string, password: string): Promise<LoginResponse> {
    return api.login(email, password);
  }

  async function completeSession(accessToken: string, refreshToken: string) {
    localStorage.setItem(STORAGE_KEY, accessToken);
    localStorage.setItem(REFRESH_STORAGE_KEY, refreshToken);
    setAuthToken(accessToken);
    const me = await api.me();
    setUser(me);
  }

  function logout() {
    const refreshToken = localStorage.getItem(REFRESH_STORAGE_KEY);
    if (refreshToken) {
      // Best-effort -- revoke the real session server-side, but don't block a local logout on
      // it (a stale/already-expired refresh token shouldn't trap the user in a "logged in" UI).
      api.logout(refreshToken).catch(() => {});
    }
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(REFRESH_STORAGE_KEY);
    setAuthToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, completeSession, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() must be used inside <AuthProvider>");
  return ctx;
}

/** Roles per Phase_12_Security_Design.md §2.2 that may trigger/reset the kill switch. */
export const KILL_SWITCH_ROLES: Role[] = [
  ROLES.SystemAdministrator,
  ROLES.PortfolioManager,
  ROLES.RiskManager,
];

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-zinc-500 text-sm">Loading…</div>;
  }
  if (!user) return null; // redirect effect above is already firing
  return <>{children}</>;
}
