import type { CSSProperties } from "react";

/**
 * spec 002 US12: a deterministic, additive per-agent accent color -- the single source of
 * truth reused by AgentFleet.tsx, AgentDetail.tsx, and TaskBoard.tsx so the same agent always
 * shows the same color everywhere. This is layered on top of the existing design tokens
 * (`--color-up`/`--color-down`/`--color-warn`, the fixed brand gradient) and never redefines
 * them -- those stay reserved for P&L/status semantics and brand identity respectively.
 *
 * Deterministic (same agent slug -> same color across reloads/sessions) via a small fixed hue
 * palette selected by a stable hash of the slug, not randomness or insertion order.
 */

// 10 hues spaced for visual distinctness at fixed saturation/lightness, tuned to sit
// comfortably against both light and dark `--panel`/`--bg` tokens (avoids `--color-up`'s green
// ~160deg and `--color-down`'s red ~350deg to prevent an agent color reading as a P&L signal).
const AGENT_HUES = [265, 210, 25, 190, 320, 45, 95, 285, 5, 235] as const;

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  }
  return hash;
}

/** HSL color string for this agent slug -- stable across calls/reloads. */
export function agentColor(agentSlug: string): string {
  const hue = AGENT_HUES[hashString(agentSlug) % AGENT_HUES.length];
  return `hsl(${hue} 70% 60%)`;
}

/** A CSS custom-property style object, spread onto an element's `style` prop so descendant
 * Tailwind arbitrary-value classes (e.g. `border-[var(--agent-color)]`) can reference it. */
export function agentColorStyle(agentSlug: string): CSSProperties {
  return { ["--agent-color" as string]: agentColor(agentSlug) } as CSSProperties;
}
