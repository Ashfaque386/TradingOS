"use client";

// Phase 1 top-nav migration: `connected`/`subtitle` used to flow into PageHeader as page-level
// props, but TopNav now lives in (app)/layout.tsx, above every page in the tree -- props can't
// reach it. Same Zustand pattern as lib/theme-store.ts, deliberately NOT persisted (this is
// per-navigation ephemeral state, not a user preference).

import { create } from "zustand";

interface ShellStatusState {
  subtitle: string;
  connected: boolean;
  setStatus: (status: { subtitle: string; connected: boolean }) => void;
}

export const useShellStatusStore = create<ShellStatusState>((set) => ({
  subtitle: "",
  connected: false,
  setStatus: (status) => set(status),
}));
