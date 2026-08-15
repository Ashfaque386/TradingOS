"use client";

import Link from "next/link";
import { cn, formatCompactINR } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { NumberTicker } from "@/components/ui/number-ticker";
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

const STATUS_STYLE: Record<StatusDot, { dot: string; badge: string; label: string }> = {
  ok: { dot: "bg-up", badge: "border-up/25 bg-up/10 text-up", label: "Connected" },
  warn: { dot: "bg-warn", badge: "border-warn/25 bg-warn/10 text-warn", label: "Not connected" },
  error: { dot: "bg-down", badge: "border-down/25 bg-down/10 text-down", label: "Error" },
};

function StatusBadge({ status, label }: { status: StatusDot; label?: string }) {
  const style = STATUS_STYLE[status];
  return (
    <Badge variant="outline" className={cn("gap-1.5", style.badge)}>
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", style.dot)} aria-hidden="true" />
      {label ?? style.label}
    </Badge>
  );
}

interface AccountCardDef {
  key: string;
  label: string;
  status: StatusDot;
  statusLabel?: string;
  panel: React.ReactNode;
}

/** REL-066: the one place Paper/Zerodha/Upstox account data renders -- replaces the 3 separately
 * stacked sections that used to repeat the same Capital+Positions shape once per account. Every
 * configured account renders as its own card, side by side, all visible at once (not hidden
 * behind tab-switching -- direct user feedback after an earlier tabbed version). A broker keeps
 * its card even when not configured (status badge + "Connect in Settings" content) so it stays
 * discoverable rather than silently disappearing, matching the connection-awareness
 * `BrokerConnectionBanner` already established (REL-036). Paper's simulated capital and a Live
 * broker's real margin are still never summed -- each card shows only its own real figures,
 * side by side, never blended into one number. */
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
  const accounts: AccountCardDef[] = [];

  if (showPaper) {
    const realizedPositive = (paperSummary?.realized_pnl_total ?? 0) >= 0;
    const unrealizedPositive = (paperSummary?.unrealized_pnl_total ?? 0) >= 0;

    accounts.push({
      key: "paper",
      label: "Paper",
      status: "ok",
      statusLabel: "Active",
      panel: (
        <div className="flex flex-col gap-4">
          {paperSummaryLoading ? (
            <div className="h-14 animate-pulse rounded-xl bg-bg" />
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Equity</p>
                <NumberTicker
                  value={paperSummary?.equity ?? 0}
                  format={formatCompactINR}
                  className="font-mono-tabular text-xl font-semibold tracking-tight text-text"
                />
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Cash</p>
                <p className="font-mono-tabular text-xl font-semibold tracking-tight text-text-dim">
                  {formatCompactINR(paperSummary?.cash ?? 0)}
                </p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Realized</p>
                <p
                  className={`font-mono-tabular text-xl font-semibold tracking-tight ${
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
                  className={`font-mono-tabular text-xl font-semibold tracking-tight ${
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
              <div className="h-14 animate-pulse rounded-xl bg-bg" />
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
              <div className="h-32 animate-pulse rounded-xl bg-bg" />
            ) : (
              <div className="max-h-[240px] overflow-y-auto">
                <PaperPositionsTable positions={paperPositions ?? []} />
              </div>
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

      accounts.push({
        key: entry.broker,
        label: entry.broker,
        status,
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
              <div className="mb-2 flex items-center justify-between">
                <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
                  Positions
                </p>
                <span className="text-[11px] text-text-faint">
                  {(positionsEntry?.positions ?? []).length}{" "}
                  {(positionsEntry?.positions ?? []).length === 1 ? "position" : "positions"}
                </span>
              </div>
              <div className="max-h-[240px] overflow-y-auto">
                <PositionsTable positions={positionsEntry?.positions ?? []} />
              </div>
            </div>
          </div>
        ),
      });
    }
  }

  if (accounts.length === 0) return null;

  return (
    <section className="flex flex-col gap-4">
      <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
        Accounts
      </p>
      <div
        className={cn(
          "grid grid-cols-1 gap-4",
          accounts.length === 2 ? "lg:grid-cols-2" : "lg:grid-cols-3",
        )}
      >
        {accounts.map((account) => (
          <Card
            key={account.key}
            title={account.label}
            action={<StatusBadge status={account.status} label={account.statusLabel} />}
          >
            {account.panel}
          </Card>
        ))}
      </div>
    </section>
  );
}
