"use client";

// Phase 2E: the palette's Dialog is mounted in AppShell (sibling to TopNav), but its open/close
// trigger needs to live in two places -- a global keydown listener and a visible button in
// TopNav -- so it needs the same "shared UI state above the page tree" pattern
// shell-status-store.ts already established. Deliberately not persisted: this is transient UI
// state, not a preference.

import { create } from "zustand";

interface CommandPaletteState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const useCommandPaletteStore = create<CommandPaletteState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));
