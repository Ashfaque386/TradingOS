"use client";

// REL-012 Phase A (2026-08-04): the theme axis is now Light/Dark only (Phase_7_Frontend_
// Architecture.md §2.7) -- the retired direction's 4-way accent picker had a `data-accent` axis
// alongside this; there is nothing left to pick beyond mode now that there's one brand gradient,
// so this store carries only `mode`. Zustand + localStorage persistence, matching the mechanism
// Phase 7 §3 already specced for this before any of it was built.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark";

interface ThemeState {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  toggleMode: () => void;
}

export const THEME_STORAGE_KEY = "tradingos-theme";

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: "light",
      setMode: (mode) => set({ mode }),
      toggleMode: () => set({ mode: get().mode === "light" ? "dark" : "light" }),
    }),
    { name: THEME_STORAGE_KEY },
  ),
);
