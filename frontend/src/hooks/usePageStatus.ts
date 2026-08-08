"use client";

// Phase 1 top-nav migration: each page calls this once, near the top of its component, with the
// exact subtitle string that used to go to <PageHeader subtitle="...">. TopNav reads the store
// this writes to.

import { useEffect } from "react";
import { useShellStatusStore } from "@/lib/shell-status-store";

export function usePageStatus(subtitle: string, connected: boolean) {
  const setStatus = useShellStatusStore((s) => s.setStatus);
  useEffect(() => {
    setStatus({ subtitle, connected });
  }, [subtitle, connected, setStatus]);
}
