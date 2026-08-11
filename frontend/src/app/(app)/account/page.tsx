"use client";

import { useQuery } from "@tanstack/react-query";
import { api, downloadAuthenticated } from "@/lib/api";
import { formatCompactINR } from "@/lib/utils";
import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { NumberTicker } from "@/components/ui/number-ticker";
import { EquityCurveChart } from "@/components/account/equity-curve-chart";
import { PaperPositionsTable } from "@/components/paper-trading/paper-positions-table";

/**
 * REL-034: the canonical "real, working ₹100,000 account" surface -- starting capital, cash,
 * margin blocked, realized/unrealized P&L, an equity curve over time, and a downloadable
 * statement, backed by src/api/routers/paper_trading.py's real /account/* endpoints. Kept
 * separate from /paper-trading, which stays focused on its own narrower fills/Shadow-Mode desk.
 */
export default function AccountPage() {
  usePageStatus("Account — Live Paper Trading Ledger", false);

  const summaryQuery = useQuery({
    queryKey: ["account-summary"],
    queryFn: () => api.accountSummary(),
    refetchInterval: 15_000,
  });
  const equityCurveQuery = useQuery({
    queryKey: ["account-equity-curve"],
    queryFn: () => api.accountEquityCurve(),
    refetchInterval: 60_000,
  });
  const positionsQuery = useQuery({
    queryKey: ["paper-positions"],
    queryFn: () => api.paperPositions(),
    refetchInterval: 15_000,
  });

  const summary = summaryQuery.data;
  const realizedPositive = (summary?.realized_pnl_total ?? 0) >= 0;
  const unrealizedPositive = (summary?.unrealized_pnl_total ?? 0) >= 0;

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <Card eyebrow="Real, Working Paper Account" title="Account Equity">
        {summaryQuery.isLoading ? (
          <div className="h-20 animate-pulse rounded-xl bg-bg" />
        ) : (
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Equity</p>
              <NumberTicker
                value={summary?.equity ?? 0}
                format={formatCompactINR}
                className="font-mono-tabular text-3xl font-semibold tracking-tight text-text"
              />
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                Starting Capital
              </p>
              <p className="font-mono-tabular text-3xl font-semibold tracking-tight text-text-dim">
                {formatCompactINR(summary?.starting_capital ?? 0)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Cash</p>
              <p className="font-mono-tabular text-3xl font-semibold tracking-tight text-text-dim">
                {formatCompactINR(summary?.cash ?? 0)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                Margin Blocked
              </p>
              <p className="font-mono-tabular text-3xl font-semibold tracking-tight text-text-dim">
                {formatCompactINR(summary?.margin_blocked ?? 0)}
              </p>
            </div>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card eyebrow="Realized" title="Realized P&L" className="lg:col-span-1">
          <NumberTicker
            value={summary?.realized_pnl_total ?? 0}
            format={formatCompactINR}
            className={`font-mono-tabular text-2xl font-semibold ${
              realizedPositive ? "text-up" : "text-down"
            }`}
          />
          {summary && Object.keys(summary.realized_pnl_by_instrument_class).length > 0 && (
            <div className="mt-3 space-y-1">
              {Object.entries(summary.realized_pnl_by_instrument_class).map(([cls, pnl]) => (
                <div key={cls} className="flex items-center justify-between text-[11px]">
                  <span className="text-text-faint">{cls}</span>
                  <span className={`font-mono-tabular ${pnl >= 0 ? "text-up" : "text-down"}`}>
                    {formatCompactINR(pnl)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card eyebrow="Mark-to-Market" title="Unrealized P&L" className="lg:col-span-1">
          <NumberTicker
            value={summary?.unrealized_pnl_total ?? 0}
            format={formatCompactINR}
            className={`font-mono-tabular text-2xl font-semibold ${
              unrealizedPositive ? "text-up" : "text-down"
            }`}
          />
          <p className="mt-3 text-[11px] text-text-faint">
            Marked to the latest live broker quote for every currently open position.
          </p>
        </Card>

        <Card
          eyebrow="Broker-Style Report"
          title="Download Statement"
          className="lg:col-span-1"
          action={
            <button
              type="button"
              onClick={() =>
                downloadAuthenticated(
                  "/api/v1/paper-trading/account/statement/export?format=csv",
                  "tradingos-paper-statement.csv",
                )
              }
              className="rounded-lg bg-bg px-3 py-1.5 text-[11px] font-medium text-text-dim transition hover:text-text"
            >
              Download CSV
            </button>
          }
        >
          <p className="text-[11px] leading-relaxed text-text-faint">
            The full real trade ledger behind every figure on this page — every fill, its
            instrument type, side, and slippage — exported as a CSV statement.
          </p>
        </Card>
      </div>

      <Card eyebrow="Since Inception" title="Equity Curve">
        {equityCurveQuery.isLoading ? (
          <div className="h-[220px] animate-pulse rounded-xl bg-bg" />
        ) : (
          <EquityCurveChart points={equityCurveQuery.data ?? []} />
        )}
      </Card>

      <Card eyebrow="Open Positions" title="Positions">
        {positionsQuery.isLoading ? (
          <div className="h-40 animate-pulse rounded-xl bg-bg" />
        ) : (
          <PaperPositionsTable positions={positionsQuery.data ?? []} />
        )}
      </Card>
    </main>
  );
}
