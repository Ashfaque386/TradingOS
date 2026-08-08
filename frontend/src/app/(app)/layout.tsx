"use client";

// Phase 1 top-nav migration: the one real shell mount point for all 9 authenticated routes,
// replacing what used to be a Sidebar+PageHeader wrapper re-rendered independently inside each
// page.tsx. RequireAuth stays the outermost element here too -- during its own `loading` state it
// renders a bare "Loading…" with no AppShell/TopNav at all, byte-identical to the old per-page
// behavior, since AppShell is RequireAuth's own child, not a sibling. /login stays outside this
// route group entirely and is unaffected.

import { RequireAuth } from "@/lib/auth";
import { AppShell } from "@/components/layout/app-shell";

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
