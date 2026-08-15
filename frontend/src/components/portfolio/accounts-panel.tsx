"use client";

import { useState } from "react";
import Link from "next/link";
import { cn, formatCompactINR } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { NumberTicker } from "@/components/ui/number-ticker";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CapitalSummary } from "@/components/portfolio/capital-summary";
import { PositionsTable } from "@/components/portfolio/positions-table";
import { PaperPositionsTable } from "@/components/paper-trading/paper-positions-table";
import type {
  AccountSummary,
  BrokerMarginEntry,
  BrokerPositionsEntry,
  PaperPosition,
} from "@/lib/api";

type StatusDot = "ok" | "warn" | "error";

const DOT_COLOR: Record<StatusDot, string> = {
  ok: "bg-up",
  warn: "bg-warn",
  error: "bg-down",
};

interface AccountTabDef {
  key: string;
  label: string;
  status: StatusDot;
  /** null = nothing real to show yet (not connected / errored), never a fabricated 0. */
  availableToTrade: number | null;
  panel: React.ReactNode;
}

/** REL-066: the one place Paper/Zerodha/Upstox account data renders -- replaces the 3 separately
 * stacked sections that used to repeat the same Capital+Positions shape once per account with a
 * single tabbed card, each tab properly labeled by account. A broker keeps its tab even when not
 * configured (status dot + "Not connected" content) so it stays discoverable rather than
 * silently disappearing -- matching the connection-awareness `BrokerConnectionBanner` already
 * established (REL-036). Paper's simulated capital and a Live broker's real margin are still
 * never summed -- the comparison strip below lists each account's own Available-to-Trade
 * side by side, never blended into one figure. */
export function AccountsPanel({
  showPaper,
  showLive,
  paperSummary,
  paperSummaryLoading,
  paperPositions,
  paperPositionsLoading,
  brokerMargins,
  brokerPositions,
}: {
  showPaper: boolean;
  showLive: boolean;
  paperSummary: AccountSummary | undefined;
  paperSummaryLoading: boolean;
  paperPositions: PaperPosition[] | undefined;
  paperPositionsLoading: boolean;
  brokerMargins: BrokerMarginEntry[];
  brokerPositions: BrokerPositionsEntry[];
}) {
  const tabs: AccountTabDef[] = [];

  if (showPaper) {
    const realizedPositive = (paperSummary?.realized_pnl_total ?? 0) >= 0;
    const unrealizedPositive = (paperSummary?.unrealized_pnl_total ?? 0) >= 0;
    const available = paperSummary
      ? paperSummary.cash - paperSummary.margin_blocked
      : null;

    tabs.push({
      key: "paper",
      label: "Paper",
      status: "ok",
      availableToTrade: available,
      panel: (
        <div className="flex flex-col gap-4">
          {paperSummaryLoading ? (
            <div className="h-16 animate-pulse rounded-xl bg-bg" />
          ) : (
            <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Equity</p>
                <NumberTicker
                  value={paperSummary?.equity ?? 0}
                  format={formatCompactINR}
                  className="font-mono-tabular text-2xl font-semibold tracking-tight text-text"
                />
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Cash</p>
                <p className="font-mono-tabular text-2xl font-semibold tracking-tight text-text-dim">
                  {formatCompactINR(paperSummary?.cash ?? 0)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Realized</p>
                <p
                  className={`font-mono-tabular text-2xl font-semibold tracking-tight ${
                    realizedPositive ? "text-up" : "text-down"
                  }`}
                >
                  {formatCompactINR(paperSummary?.realized_pnl_total ?? 0)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                  Unrealized
                </p>
                <p
                  className={`font-mono-tabular text-2xl font-semibold tracking-tight ${
                    unrealizedPositive ? "text-up" : "text-down"
                  }`}
                >
                  {formatCompactINR(paperSummary?.unrealized_pnl_total ?? 0)}
                </p>
              </div>
            </div>
          )}

          <div className="border-t border-card-edge pt-4">
            {paperSummaryLoading ? (
              <div className="h-16 animate-pulse rounded-xl bg-bg" />
            ) : (
              <CapitalSummary
                used={paperSummary?.margin_blocked ?? 0}
                available={(paperSummary?.cash ?? 0) - (paperSummary?.margin_blocked ?? 0)}
              />
            )}
          </div>

          <div className="border-t border-card-edge pt-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
                Positions
              </p>
              <Link
                href="/account"
                className="text-[11px] font-medium text-text-dim underline underline-offset-2 hover:text-text"
              >
                Full ledger →
              </Link>
            </div>
            {paperPositionsLoading ? (
              <div className="h-40 animate-pulse rounded-xl bg-bg" />
            ) : (
              <PaperPositionsTable positions={paperPositions ?? []} />
            )}
          </div>
        </div>
      ),
    });
  }

  if (showLive) {
    for (const entry of brokerMargins) {
      const positionsEntry = brokerPositions.find((p) => p.broker === entry.broker);
      const status: StatusDot = !entry.configured ? "warn" : entry.error ? "error" : "ok";
      const available =
        entry.configured && !entry.error && entry.margin ? entry.margin.available_margin : null;

      tabs.push({
        key: entry.broker,
        label: entry.broker,
        status,
        availableToTrade: available,
        panel: !entry.configured ? (
          <div className="flex h-32 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-card-edge text-center">
            <p className="text-xs text-text-faint">{entry.broker} is not connected.</p>
            <Link
              href="/settings"
              className="text-[11px] font-medium text-text-dim underline underline-offset-2 hover:text-text"
            >
              Connect in Settings →
            </Link>
          </div>
        ) : entry.error ? (
          <div className="flex h-32 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-down/30 text-center">
            <p className="text-xs text-down">{entry.error}</p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <CapitalSummary
              used={entry.margin?.used_margin ?? 0}
              available={entry.margin?.available_margin ?? 0}
            />
            <div className="border-t border-card-edge pt-4">
              <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
                Positions
              </p>
              <PositionsTable positions={positionsEntry?.positions ?? []} />
            </div>
          </div>
        ),
      });
    }
  }

  const [active, setActive] = useState(tabs[0]?.key ?? "");
  const activeKey = tabs.some((t) => t.key === active) ? active : (tabs[0]?.key ?? "");

  if (tabs.length === 0) return null;

  return (
    <Card eyebrow="Accounts" title="Paper, Zerodha & Upstox">
      <div className="mb-5 flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <div
            key={tab.key}
            className="flex items-center gap-2 rounded-lg border border-card-edge bg-bg px-3 py-2"
          >
            <span
              className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_COLOR[tab.status])}
              aria-hidden="true"
            />
            <span className="text-[11px] font-medium text-text-dim">{tab.label}</span>
            <span className="font-mono-tabular text-[11px] text-text-faint">
              {tab.availableToTrade !== null ? formatCompactINR(tab.availableToTrade) : "—"}
            </span>
          </div>
        ))}
      </div>

      <Tabs value={activeKey} onValueChange={(v) => setActive(v as string)}>
        <TabsList>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.key} value={tab.key}>
              <span
                className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_COLOR[tab.status])}
                aria-hidden="true"
              />
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {tabs.map((tab) => (
          <TabsContent key={tab.key} value={tab.key} className="mt-4">
            {tab.panel}
          </TabsContent>
        ))}
      </Tabs>
    </Card>
  );
}
