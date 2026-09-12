/**
 * spec 002 US6: a small, consistent color tag per `OrganizationalEvent.event_type`, so the
 * Activity Stream is scannable at a glance -- extends TradingOS's existing semantic tokens
 * (`up`/`down`/`warn`, the brand accent already used for "active"/CEO-adjacent state in
 * graph-flowchart.tsx's `STATE_STYLES`) rather than inventing a new palette.
 */

export type EventTone = "up" | "down" | "warn" | "brand" | "neutral";

const TONE_CLASSES: Record<EventTone, string> = {
  up: "bg-up/10 text-up",
  down: "bg-destructive/10 text-destructive",
  warn: "bg-warn/10 text-warn",
  brand: "bg-brand-via/10 text-brand-via",
  neutral: "bg-panel text-text-faint",
};

export function eventTone(eventType: string): EventTone {
  if (
    eventType.endsWith(".failed") ||
    eventType.endsWith(".rejected") ||
    eventType === "task.blocked"
  )
    return "down";
  if (
    eventType.endsWith(".satisfied") ||
    eventType.endsWith(".completed") ||
    eventType.endsWith(".approved") ||
    eventType.endsWith(".ready")
  )
    return "up";
  if (
    eventType.endsWith(".waiting_for_dependency") ||
    eventType.endsWith(".retrying") ||
    eventType.endsWith(".requested")
  )
    return "warn";
  if (
    eventType.startsWith("ceo.") ||
    eventType.startsWith("plan.") ||
    eventType.startsWith("agent.") ||
    eventType.startsWith("organization.plan")
  )
    return "brand";
  return "neutral";
}

export function eventToneClassName(eventType: string): string {
  return TONE_CLASSES[eventTone(eventType)];
}

/** For a caller that already resolved a tone (e.g. `ceoNarration.ts`'s precomputed
 * `NarrationLine.tone`) rather than holding the raw event_type string. */
export function toneClassName(tone: EventTone): string {
  return TONE_CLASSES[tone];
}
