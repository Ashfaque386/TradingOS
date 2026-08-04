import type { ThemeMode } from "@/lib/theme-store";

// REL-012 Phase D: canvas-based chart libraries (lightweight-charts, ECharts) need literal color
// strings in their JS config objects, not CSS custom-property references -- they don't read the
// DOM's computed style themselves. This mirrors the mode-scoped token values from globals.css so
// chart components can react to `useThemeStore`'s `mode` directly (cheap, synchronous) instead of
// a `getComputedStyle`/MutationObserver read. Keep in sync with globals.css's
// `:root[data-mode="light"|"dark"]` blocks by hand -- there are only 4 values per mode.
export interface ChartColors {
  text: string;
  textDim: string;
  textFaint: string;
  /** Card border strength -- matches --card-edge. */
  grid: string;
  /** A visually stronger line than `grid`, for axis lines that need to read clearly. */
  axisLine: string;
  /** A visually weaker line than `grid`, for internal split-lines that shouldn't compete. */
  splitLine: string;
  panel: string;
}

const LIGHT: ChartColors = {
  text: "#111111",
  textDim: "#666666",
  textFaint: "#999999",
  grid: "rgba(17, 17, 17, 0.08)",
  axisLine: "rgba(17, 17, 17, 0.15)",
  splitLine: "rgba(17, 17, 17, 0.05)",
  panel: "#ffffff",
};

const DARK: ChartColors = {
  text: "#f5f5f7",
  textDim: "#a1a1aa",
  textFaint: "#71717a",
  grid: "rgba(255, 255, 255, 0.08)",
  axisLine: "rgba(255, 255, 255, 0.15)",
  splitLine: "rgba(255, 255, 255, 0.06)",
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
