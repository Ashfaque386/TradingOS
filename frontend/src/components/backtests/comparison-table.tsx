"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { METRICS } from "./metric-grid";
import type { BacktestSummary } from "@/lib/api";

export interface ComparisonRow {
  id: string;
  label: string;
  backtest: BacktestSummary;
}

/**
 * REL-040/041/042: sortable KPI comparison table shared by the per-strategy cross-run card, the
 * cross-strategy "latest per strategy" card, and (REL-042) the multi-run comparison workspace --
 * `selectedIds`/`onToggle` are optional so this component works as a plain read-only table until
 * REL-042 wires selection in.
 */
export function BacktestComparisonTable({
  rows,
  selectedIds,
  onToggle,
  maxSelected,
}: {
  rows: ComparisonRow[];
  selectedIds?: Set<string>;
  onToggle?: (id: string) => void;
  maxSelected?: number;
}) {
  const [sortKey, setSortKey] = useState<keyof BacktestSummary>("sharpe_ratio");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const av = a.backtest[sortKey];
      const bv = b.backtest[sortKey];
      const an = typeof av === "number" ? av : sortDir === "desc" ? -Infinity : Infinity;
      const bn = typeof bv === "number" ? bv : sortDir === "desc" ? -Infinity : Infinity;
      return sortDir === "desc" ? bn - an : an - bn;
    });
  }, [rows, sortKey, sortDir]);

  if (rows.length === 0) {
    return <p className="text-xs text-text-faint">Nothing to compare yet.</p>;
  }

  const selectable = !!selectedIds && !!onToggle;

  return (
    <div className="overflow-x-auto">
      <Table className="text-[11px]">
        <TableHeader>
          <TableRow className="text-[9px] uppercase tracking-wider text-text-faint hover:bg-transparent">
            {selectable && <TableHead className="h-auto w-6 px-0 pb-2 font-normal" />}
            <TableHead className="h-auto px-0 pb-2 pr-3 font-normal">Run</TableHead>
            {METRICS.map((m) => (
              <TableHead
                key={m.key}
                onClick={() => {
                  if (sortKey === m.key) {
                    setSortDir(sortDir === "desc" ? "asc" : "desc");
                  } else {
                    setSortKey(m.key);
                    setSortDir("desc");
                  }
                }}
                className="h-auto cursor-pointer select-none px-0 pb-2 pr-3 text-right font-normal hover:text-text-dim"
              >
                <span className="inline-flex items-center gap-0.5">
                  {m.label}
                  {sortKey === m.key &&
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
          {sortedRows.map(({ id, label, backtest }) => {
            const isSelected = selectedIds?.has(id) ?? false;
            const disableSelect =
              selectable && !isSelected && !!maxSelected && (selectedIds?.size ?? 0) >= maxSelected;
            return (
              <TableRow key={id} className="border-card-edge">
                {selectable && (
                  <TableCell className="w-6 px-0 py-1.5">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      disabled={disableSelect}
                      onChange={() => onToggle!(id)}
                      className="h-3 w-3 accent-brand-via disabled:opacity-30"
                    />
                  </TableCell>
                )}
                <TableCell className="px-0 py-1.5 pr-3 text-text-dim">{label}</TableCell>
                {METRICS.map(({ key, fmt }) => {
                  const raw = backtest[key];
                  return (
                    <TableCell
                      key={key}
                      className={cn(
                        "px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint",
                        sortKey === key && "text-text-dim",
                      )}
                    >
                      {typeof raw === "number" ? fmt(raw) : "—"}
                    </TableCell>
                  );
                })}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
