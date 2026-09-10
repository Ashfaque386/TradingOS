"use client";

import { useMemo } from "react";
import type { OrgDependency, OrgTask } from "@/lib/api";
import { Card } from "@/components/ui/card";

const COL_W = 190;
const ROW_H = 64;
const NODE_W = 168;
const NODE_H = 44;

function layer(tasks: OrgTask[], deps: OrgDependency[]): Map<string, number> {
  const prereqs = new Map<string, string[]>();
  for (const d of deps) {
    prereqs.set(d.dependent_task_id, [...(prereqs.get(d.dependent_task_id) ?? []), d.prerequisite_task_id]);
  }
  const depth = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0; // defensive: the backend guarantees a DAG
    seen.add(id);
    const ps = prereqs.get(id) ?? [];
    const d = ps.length === 0 ? 0 : 1 + Math.max(...ps.map((p) => visit(p, seen)));
    depth.set(id, d);
    return d;
  };
  for (const t of tasks) visit(t.task_id, new Set());
  return depth;
}

function nodeColor(status: string): { fill: string; stroke: string } {
  if (status === "completed") return { fill: "rgb(16 185 129 / 0.14)", stroke: "rgb(16 185 129)" };
  if (["failed", "blocked", "cancelled"].includes(status))
    return { fill: "rgb(239 68 68 / 0.14)", stroke: "rgb(239 68 68)" };
  if (status === "running") return { fill: "rgb(14 165 233 / 0.16)", stroke: "rgb(14 165 233)" };
  if (status.startsWith("waiting")) return { fill: "rgb(245 158 11 / 0.14)", stroke: "rgb(245 158 11)" };
  return { fill: "var(--color-bg)", stroke: "var(--color-card-edge)" };
}

/** FR-081: a layered task DAG driven entirely by real task status + real dependency `state` --
 * no simulated motion. A running node pulses and a satisfied dependency edge is drawn solid;
 * everything else is static. Honours `prefers-reduced-motion` (FR-170) by disabling the pulse. */
export function OrgTaskGraph({
  tasks,
  dependencies,
}: {
  tasks: OrgTask[];
  dependencies: OrgDependency[];
}) {
  const reduceMotion =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const { positions, width, height } = useMemo(() => {
    const depth = layer(tasks, dependencies);
    const perCol = new Map<number, number>();
    const pos = new Map<string, { x: number; y: number }>();
    for (const t of [...tasks].sort((a, b) => (depth.get(a.task_id)! - depth.get(b.task_id)!))) {
      const col = depth.get(t.task_id) ?? 0;
      const row = perCol.get(col) ?? 0;
      perCol.set(col, row + 1);
      pos.set(t.task_id, { x: col * COL_W + 16, y: row * ROW_H + 16 });
    }
    const cols = Math.max(1, ...[...depth.values()].map((d) => d + 1));
    const rows = Math.max(1, ...[...perCol.values()]);
    return { positions: pos, width: cols * COL_W + 16, height: rows * ROW_H + 16 };
  }, [tasks, dependencies]);

  const label = new Map(tasks.map((t) => [t.task_id, t]));

  return (
    <Card eyebrow="Plan" title="Task graph">
      {tasks.length === 0 ? (
        <p className="text-[11px] italic text-text-faint">No plan yet for this run.</p>
      ) : (
        <div className="overflow-x-auto">
          <svg width={width} height={height} className="min-w-full" role="img" aria-label="Organisation task graph">
            {reduceMotion ? null : (
              <style>{`@keyframes org-pulse{0%,100%{opacity:1}50%{opacity:.45}}`}</style>
            )}
            {dependencies.map((d, i) => {
              const a = positions.get(d.prerequisite_task_id);
              const b = positions.get(d.dependent_task_id);
              if (!a || !b) return null;
              const satisfied = d.state === "satisfied";
              return (
                <line
                  key={i}
                  x1={a.x + NODE_W}
                  y1={a.y + NODE_H / 2}
                  x2={b.x}
                  y2={b.y + NODE_H / 2}
                  stroke={satisfied ? "rgb(16 185 129)" : "var(--color-card-edge)"}
                  strokeWidth={satisfied ? 2 : 1}
                  strokeDasharray={satisfied ? undefined : "4 3"}
                />
              );
            })}
            {tasks.map((t) => {
              const p = positions.get(t.task_id);
              if (!p) return null;
              const c = nodeColor(t.status);
              const pulsing = !reduceMotion && t.status === "running";
              return (
                <g key={t.task_id} transform={`translate(${p.x} ${p.y})`}>
                  <rect
                    width={NODE_W}
                    height={NODE_H}
                    rx={10}
                    fill={c.fill}
                    stroke={c.stroke}
                    strokeWidth={1.5}
                    style={pulsing ? { animation: "org-pulse 1.6s ease-in-out infinite" } : undefined}
                  />
                  <text x={10} y={17} fontSize={10} fontWeight={600} fill="var(--color-text)">
                    {(label.get(t.task_id)?.capability ?? "").slice(0, 22)}
                  </text>
                  <text x={10} y={31} fontSize={9} fill="var(--color-text-muted)">
                    {t.assigned_agent.slice(0, 20)}
                  </text>
                  <text x={10} y={41} fontSize={8} fill="var(--color-text-faint)">
                    {t.status}
                    {t.ran_concurrently ? " · ∥" : ""}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </Card>
  );
}
