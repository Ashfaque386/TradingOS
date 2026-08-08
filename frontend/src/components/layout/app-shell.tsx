"use client";

// Phase 1 top-nav migration: deliberately thin -- owns TopNav only, not <main>, so every page's
// own existing <main> wrapper (which varies: Portfolio's fixed-grid layout, Audit's
// permission-gated fallback, Chat's xl:grid-cols-12 panel) carries over completely unchanged.

import { TopNav } from "@/components/layout/top-nav";
import { CommandPalette } from "@/components/layout/command-palette";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <TopNav />
      <CommandPalette />
      {children}
    </div>
  );
}
