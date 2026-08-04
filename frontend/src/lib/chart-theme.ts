import type { ThemeMode } from "@/lib/theme-store";

// REL-012 Phase D: canvas-based chart libraries (lightweight-charts, ECharts) need literal color
// strings in their JS config objects, not CSS custom-property references -- they don't read the
// DOM's computed style themselves. This mirrors the mode-scoped token values from globals.css so
// chart components can react to `useThemeStore`'s `mode` directly (cheap, synchronous) instead of
// a `getComputedStyle`/MutationObserver read. Keep in sync with globals.css's
// `:root[data-mode="light"|"dark"]` blocks by hand -- there are only 4 values per mode.
export interface ChartColors {
  text: string;
  textFaint: string;
  grid: string;
  panel: string;
}

const LIGHT: ChartColors = {
  text: "#111111",
  textFaint: "#999999",
  grid: "rgba(17, 17, 17, 0.08)",
  panel: "#ffffff",
};

const DARK: ChartColors = {
  text: "#f5f5f7",
  textFaint: "#71717a",
  grid: "rgba(255, 255, 255, 0.08)",
  panel: "#16161c",
};

// Financial semantics are fixed across both modes (Phase 7 §1.1 -- a cosmetic theme preference
// must never touch a P&L color), matching globals.css's plain `:root` (not mode-scoped) block.
export const CHART_COLOR_UP = "#10b981";
export const CHART_COLOR_DOWN = "#f43f5e";
export const CHART_COLOR_WARN = "#f59e0b";

export function getChartColors(mode: ThemeMode): ChartColors {
  return mode === "dark" ? DARK : LIGHT;
}
