"use client";

import { useLayoutEffect } from "react";
import { useThemeStore } from "@/lib/theme-store";

/** REL-012 Phase A/E (2026-08-04, revised): keeps `<html data-mode>` in sync with the persisted
 * theme store, including setting it correctly on first mount -- no flash of the wrong theme.
 *
 * Previously this ran via a separate pre-hydration inline `<script>` in app/layout.tsx's <head>
 * (the standard next-themes-style pattern), with this component only handling *reactive*
 * changes after that. Removed during REL-012 E12.8's Cypress regression pass: that inline script
 * caused a real hydration-mismatch crash in this Next.js version (React threw and regenerated
 * the whole tree on the first discrete client interaction after load -- confirmed reproducible
 * with the script in every form tried: next/script's Script component with children, the same
 * with dangerouslySetInnerHTML, and a plain <script> tag with dangerouslySetInnerHTML; confirmed
 * absent when the script was removed entirely). Invisible to every manual browser check this
 * session, since those always exercised an already-hydrated page rather than a genuinely cold
 * load immediately followed by an interaction -- exactly what Cypress's login flow does.
 *
 * `useLayoutEffect` (not `useEffect`) is what actually avoids the flash now: it fires
 * synchronously after the DOM updates but before the browser paints, so even though this runs
 * after hydration completes (not before, like the old script did), no frame is ever painted with
 * the wrong `data-mode`. Zustand's `persist` middleware hydrates the store synchronously from
 * localStorage during module evaluation in the browser (no `skipHydration` is set), so `mode`
 * already reflects the real persisted value by the time this layout effect runs on first mount --
 * not the store's hardcoded "light" default. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const mode = useThemeStore((state) => state.mode);

  useLayoutEffect(() => {
    document.documentElement.dataset.mode = mode;
  }, [mode]);

  return <>{children}</>;
}
