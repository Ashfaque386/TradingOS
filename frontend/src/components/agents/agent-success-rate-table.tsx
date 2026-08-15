"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AgentAnalyticsSummaryRow } from "@/lib/api";

type SortKey = "total_runs" | "success_rate" | "avg_duration_seconds" | "p95_duration_seconds";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "total_runs", label: "Runs" },
  { key: "success_rate", label: "Success Rate" },
  { key: "avg_duration_seconds", label: "Avg Duration" },
  { key: "p95_duration_seconds", label: "P95 Duration" },
];

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

function successRateColor(rate: number | null): string {
  if (rate === null) return "text-text-faint";
  if (rate >= 0.9) return "text-up";
  if (rate >= 0.6) return "text-warn";
  return "text-down";
}

/** REL-068: real per-agent execution stats (GET /agents/analytics/summary), sortable, reusing
 * the shared Table primitives + the sort-icon interaction already established by
 * components/backtests/comparison-table.tsx (a new table, not that one directly -- the metric
 * shape here is agent-run stats, not backtest KPIs). */
export function AgentSuccessRateTable({ rows }: { rows: AgentAnalyticsSummaryRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("total_runs");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const an = av === null ? -Infinity : av;
      const bn = bv === null ? -Infinity : bv;
      return sortDir === "desc" ? bn - an : an - bn;
    });
  }, [rows, sortKey, sortDir]);

  if (rows.length === 0) {
    return (
      <div className="flex h-[140px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
        <p className="text-xs text-text-faint">
          No agent runs in this window yet — trigger a research cycle to start collecting real
          execution data.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table className="text-[11px]">
        <TableHeader>
          <TableRow className="text-[9px] uppercase tracking-wider text-text-faint hover:bg-transparent">
            <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Agent</TableHead>
            {COLUMNS.map((col) => (
              <TableHead
                key={col.key}
                onClick={() => {
                  if (sortKey === col.key) {
                    setSortDir(sortDir === "desc" ? "asc" : "desc");
                  } else {
                    setSortKey(col.key);
                    setSortDir("desc");
                  }
                }}
                className="h-auto cursor-pointer select-none px-0 pb-2 pr-3 text-right font-normal hover:text-text-dim"
              >
                <span className="inline-flex items-center gap-0.5">
                  {col.label}
                  {sortKey === col.key &&
                    (sortDir === "desc" ? (
                      <ArrowDown className="h-2.5 w-2.5" />
                    ) : (
                      <ArrowUp className="h-2.5 w-2.5" />
                    ))}
                </span>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sortedRows.map((row) => (
            <TableRow key={row.agent_name} className="border-card-edge">
              <TableCell className="px-0 py-1.5 pr-3 font-medium text-text-dim">
                {row.display_name}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 text-right font-mono-tabular",
                  sortKey === "total_runs" ? "text-text-dim" : "text-text-faint",
                )}
              >
                {row.total_runs}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 text-right font-mono-tabular font-semibold",
                  successRateColor(row.success_rate),
                )}
              >
                {row.success_rate !== null ? `${(row.success_rate * 100).toFixed(0)}%` : "—"}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 text-right font-mono-tabular",
                  sortKey === "avg_duration_seconds" ? "text-text-dim" : "text-text-faint",
                )}
              >
                {formatDuration(row.avg_duration_seconds)}
              </TableCell>
              <TableCell
                className={cn(
                  "px-0 py-1.5 pr-3 text-right font-mono-tabular",
                  sortKey === "p95_duration_seconds" ? "text-text-dim" : "text-text-faint",
                )}
              >
                {formatDuration(row.p95_duration_seconds)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
