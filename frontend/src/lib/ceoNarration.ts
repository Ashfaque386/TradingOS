import type { OrgEvent } from "@/lib/api";
import { eventTone, type EventTone } from "@/lib/eventTone";

/**
 * spec 002 US13: a short, present-tense CEO narration line per real `OrganizationalEvent` --
 * every sentence traces back to a real event's own payload fields (agent slug, capability,
 * decision reason, departments, task count), never a client-side fabrication. Reuses US6's
 * `eventTone` for the narration feed's own tone tag, so the two surfaces stay visually
 * consistent. Only the CEO-relevant families named in spec.md US13 are narrated (`plan.*`,
 * `task.started` -- the real event this codebase emits at dispatch time, `ceo.decision.*`,
 * `ceo.conflict_detected`, `approval.*`); anything else returns `null` rather than a generic
 * "something happened" line.
 */

export interface NarrationLine {
  sequence: number;
  text: string;
  tone: EventTone;
  occurred_at: string;
}

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}

/** `displayNameByAgent` maps a real `KNOWN_AGENTS` slug -> its `display_name` (from the Agent
 * Registry, already fetched elsewhere) -- falls back to the raw slug if not found, never a
 * fabricated name. */
export function narrateEvent(
  e: OrgEvent,
  displayNameByAgent: Record<string, string>,
): string | null {
  const p = e.payload ?? {};
  const reason = str(p.reason);

  if (e.event_type === "organization.plan.created") {
    const taskCount = num(p.task_count);
    const departments = Array.isArray(p.departments) ? (p.departments as unknown[]) : [];
    const deptText = departments.length > 0 ? ` across ${departments.join(", ")}` : "";
    return `Drafting a plan of ${taskCount ?? "several"} task${taskCount === 1 ? "" : "s"}${deptText}.`;
  }

  if (e.event_type === "task.started") {
    const agentSlug = str(p.assigned_agent);
    const capability = str(p.capability);
    if (agentSlug) {
      const name = displayNameByAgent[agentSlug] ?? agentSlug;
      return capability ? `Delegating ${capability.replace(/_/g, " ")} to ${name}.` : `Delegating to ${name}.`;
    }
    return null;
  }

  if (e.event_type === "ceo.decision.created") {
    const summary = str(p.summary);
    return summary ?? reason;
  }

  if (e.event_type === "ceo.conflict_detected") {
    const description = str(p.description);
    return description ? `Conflict detected: ${description}` : reason;
  }

  if (e.event_type === "approval.requested") {
    return "Requesting human approval before proceeding.";
  }
  if (e.event_type === "approval.approved") {
    return reason ?? "Approval granted.";
  }
  if (e.event_type === "approval.rejected") {
    return reason ?? "Approval rejected.";
  }

  return null;
}

export function narrationFeed(
  events: OrgEvent[],
  displayNameByAgent: Record<string, string>,
): NarrationLine[] {
  const lines: NarrationLine[] = [];
  for (const e of events) {
    const text = narrateEvent(e, displayNameByAgent);
    if (text) {
      lines.push({ sequence: e.sequence, text, tone: eventTone(e.event_type), occurred_at: e.occurred_at });
    }
  }
  return lines.sort((a, b) => b.sequence - a.sequence);
}
