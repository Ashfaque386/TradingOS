"use client";

// Auth context (Phase 4 exit-criteria gap: RBAC). Token lives in localStorage, not the httpOnly
// Secure SameSite cookie Phase_12_Security_Design.md §2.1 specs -- a documented MVP
// simplification (see src/core/security.py's module docstring on the backend side for the rest
// of what's deferred: MFA, Vault-issued signing keys, refresh-token rotation). Real Next.js
// middleware-based route protection needs a cookie it can read at the edge; a localStorage token
// can only be checked client-side, which is what RequireAuth below does.

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setAuthToken, ROLES, type Role } from "@/lib/api";

interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY = "tradingos_access_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (!stored) {
      setLoading(false);
      return;
    }
    setAuthToken(stored);
    api
      .me()
      .then((me) => setUser(me))
      .catch(() => {
        setAuthToken(null);
        localStorage.removeItem(STORAGE_KEY);
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const { access_token } = await api.login(email, password);
    localStorage.setItem(STORAGE_KEY, access_token);
    setAuthToken(access_token);
    const me = await api.me();
    setUser(me);
  }

  function logout() {
    localStorage.removeItem(STORAGE_KEY);
    setAuthToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
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
