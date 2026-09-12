"use client";

import { motion } from "framer-motion";
import { Clock, Loader2, PauseCircle, Ban, RotateCw, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api, type OrgTask } from "@/lib/api";
import { agentColor } from "@/lib/agentColor";
import { cn } from "@/lib/utils";
import { staggerContainer, staggerItem } from "@/lib/motion";
import { taskStateExplainer } from "./AgentDetail";

/** spec 002 US5: a read-only adaptation of components/strategies/kanban-board.tsx's column
 * shell -- same grid/column/count-badge pattern, no drag-and-drop (a Task's status is
 * system-driven by the real task engine, never dragged by a human). Groups the same
 * `GET .../tasks` response already fetched elsewhere on the run page; no new backend surface. */
const COLUMNS: { statuses: string[]; label: string; icon: typeof Clock }[] = [
  { statuses: ["created", "planned", "queued", "ready"], label: "Queued", icon: Clock },
  { statuses: ["running"], label: "Running", icon: Loader2 },
  { statuses: ["waiting_for_dependency"], label: "Waiting", icon: PauseCircle },
  { statuses: ["blocked"], label: "Blocked", icon: Ban },
  { statuses: ["retrying"], label: "Retrying", icon: RotateCw },
  { statuses: ["escalated"], label: "Escalated", icon: AlertTriangle },
  { statuses: ["completed"], label: "Completed", icon: CheckCircle2 },
  { statuses: ["failed", "cancelled"], label: "Failed", icon: XCircle },
];

export function TaskBoard({ runId }: { runId: string }) {
  const tasksQuery = useQuery({
    queryKey: ["org-tasks", runId],
    queryFn: () => api.orgTasks(runId),
    refetchInterval: 5_000,
  });

  const tasks = tasksQuery.data ?? [];
  if (tasksQuery.isLoading) return <div className="h-40 animate-pulse rounded-card bg-bg" />;

  const byColumn = (statuses: string[]) => tasks.filter((t) => statuses.includes(t.status));

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {COLUMNS.map((col) => {
        const items = byColumn(col.statuses);
        return (
          <motion.div
            key={col.label}
            initial="hidden"
            animate="visible"
            variants={staggerContainer}
            className="flex max-h-[calc(100vh-320px)] min-h-[160px] flex-col gap-2 rounded-2xl border border-card-edge bg-bg p-3"
          >
            <div className="mb-1 flex flex-shrink-0 items-center justify-between px-0.5">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-dim">
                <col.icon className="h-3 w-3" />
                {col.label}
              </span>
              <span className="rounded-full bg-panel px-1.5 py-0.5 text-[10px] text-text-faint">
                {items.length}
              </span>
            </div>
            <div className="flex flex-1 flex-col gap-2 overflow-y-auto pr-0.5">
              {items.length === 0 && (
                <div className="flex flex-1 items-center justify-center py-6 text-center text-[10px] text-text-faint">
                  Empty
                </div>
              )}
              {items.map((t) => (
                <TaskCard key={t.task_id} task={t} />
              ))}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

function TaskCard({ task }: { task: OrgTask }) {
  const explanation = taskStateExplainer({
    status: task.status,
    blocked_reason: task.blocked_reason,
    failure_reason: task.failure_reason,
    retry_count: task.retry_count,
    depends_on: task.depends_on,
  });

  return (
    <motion.div
      variants={staggerItem}
      className="rounded-xl border border-card-edge bg-panel p-2.5 text-xs"
      style={{ borderLeftColor: agentColor(task.assigned_agent), borderLeftWidth: 3 }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium text-text">{task.assigned_agent}</span>
        <span className="shrink-0 text-[10px] text-text-faint">P{task.priority}</span>
      </div>
      <div className={cn("mt-0.5 truncate text-text-muted", "text-[11px]")}>{task.capability}</div>
      {task.started_at && (
        <div className="mt-1 text-[10px] text-text-faint">
          started {new Date(task.started_at).toLocaleTimeString()}
        </div>
      )}
      {explanation && <div className="mt-1 text-[10px] text-text-faint">{explanation}</div>}
    </motion.div>
  );
}
