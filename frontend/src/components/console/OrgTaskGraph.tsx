"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { OrgDependency, OrgTask } from "@/lib/api";
import { Card } from "@/components/ui/card";

const COL_W = 190;
const ROW_H = 64;
const NODE_W = 168;
const NODE_H = 44;
const MIN_SCALE = 0.4;
const MAX_SCALE = 3;
const ACTIVATION_FLASH_MS = 1400;

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

function depKey(d: OrgDependency): string {
  return `${d.prerequisite_task_id}->${d.dependent_task_id}`;
}

/** FR-081 + spec 002 US14: a layered task DAG driven entirely by real task status + real
 * dependency `state` -- no simulated motion or replay. A running node pulses; a satisfied
 * dependency edge is drawn solid and, at the moment it *transitions* from unsatisfied to
 * satisfied (driven by the real `dependency.satisfied` event already invalidating this run's
 * `org-dependencies` query via `useOrganizationStream`), briefly flashes to make that live
 * activation visible rather than silently snapping. Pan/zoom is a viewport transform only -- the
 * underlying depth/position computation is untouched, so `GET .../dependencies` still matches
 * every rendered node/edge exactly. Honours `prefers-reduced-motion` (FR-170) by disabling both
 * the running-node pulse and the activation flash. */
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

  // --- US14 (T085): flag edges that just flipped to `satisfied` since the last render, so they
  // get a brief activation flash instead of an instant, unremarkable color swap. ---
  const prevSatisfiedRef = useRef<Set<string>>(new Set());
  const [justActivated, setJustActivated] = useState<Set<string>>(new Set());
  useEffect(() => {
    const currentSatisfied = new Set(dependencies.filter((d) => d.state === "satisfied").map(depKey));
    const newlySatisfied = [...currentSatisfied].filter((k) => !prevSatisfiedRef.current.has(k));
    prevSatisfiedRef.current = currentSatisfied;
    if (newlySatisfied.length === 0 || reduceMotion) return;
    setJustActivated((prev) => new Set([...prev, ...newlySatisfied]));
    const timer = setTimeout(() => {
      setJustActivated((prev) => {
        const next = new Set(prev);
        for (const k of newlySatisfied) next.delete(k);
        return next;
      });
    }, ACTIVATION_FLASH_MS);
    return () => clearTimeout(timer);
  }, [dependencies, reduceMotion]);

  // --- US14 (T084): pan/zoom viewport transform, layered on top of the existing SVG -- the
  // node/edge coordinates above are never recomputed for this, only the viewport's own
  // translate/scale changes. ---
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(
    null,
  );

  const onWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const delta = -e.deltaY * 0.0015;
    setView((v) => ({ ...v, scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale + delta)) }));
  };
  const onMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: view.x, origY: view.y };
  };
  const onMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    setView((v) => ({ ...v, x: dragRef.current!.origX + dx, y: dragRef.current!.origY + dy }));
  };
  const endDrag = () => {
    dragRef.current = null;
  };
  const resetView = () => setView({ x: 0, y: 0, scale: 1 });

  return (
    <Card
      eyebrow="Plan"
      title="Task graph"
      action={
        tasks.length > 0 ? (
          <button
            type="button"
            onClick={resetView}
            className="rounded-md border border-card-edge px-1.5 py-0.5 text-[11px] text-text-faint hover:text-text-dim"
          >
            Reset view
          </button>
        ) : undefined
      }
    >
      {tasks.length === 0 ? (
        <p className="text-[11px] italic text-text-faint">No plan yet for this run.</p>
      ) : (
        <div className="overflow-hidden rounded-md border border-card-edge/50">
          <svg
            width="100%"
            height={Math.min(height, 420)}
            viewBox={`0 0 ${width} ${height}`}
            className="min-w-full cursor-grab active:cursor-grabbing"
            role="img"
            aria-label="Organisation task graph (scroll to zoom, drag to pan)"
            onWheel={onWheel}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={endDrag}
            onMouseLeave={endDrag}
          >
            {reduceMotion ? null : (
              <style>{`
                @keyframes org-pulse{0%,100%{opacity:1}50%{opacity:.45}}
                @keyframes org-edge-activate{0%{stroke-width:5;opacity:1}100%{stroke-width:2;opacity:1}}
              `}</style>
            )}
            <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
              {dependencies.map((d, i) => {
                const a = positions.get(d.prerequisite_task_id);
                const b = positions.get(d.dependent_task_id);
                if (!a || !b) return null;
                const satisfied = d.state === "satisfied";
                const activating = justActivated.has(depKey(d));
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
                    style={{
                      transition: "stroke 400ms ease-out, stroke-width 400ms ease-out",
                      animation: activating ? "org-edge-activate 1.4s ease-out" : undefined,
                    }}
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
            </g>
          </svg>
        </div>
      )}
    </Card>
  );
}
