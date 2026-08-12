"use client";

// REL-036: which account(s) the app is currently showing data for -- global, not per-page, since
// the whole point is that every account-data page (dashboard, orders, account, paper trading)
// stays in sync on the same selection rather than forcing a re-pick on every navigation. Zustand
// + localStorage persistence, matching theme-store.ts's exact pattern. Defaults to "both" -- the
// safest default is showing everything, not silently hiding a real account's data.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type AccountScope = "paper" | "live" | "both";

interface AccountScopeState {
  scope: AccountScope;
  setScope: (scope: AccountScope) => void;
}

export const ACCOUNT_SCOPE_STORAGE_KEY = "tradingos-account-scope";

export const useAccountScopeStore = create<AccountScopeState>()(
  persist(
    (set) => ({
      scope: "both",
      setScope: (scope) => set({ scope }),
    }),
    { name: ACCOUNT_SCOPE_STORAGE_KEY },
  ),
);
