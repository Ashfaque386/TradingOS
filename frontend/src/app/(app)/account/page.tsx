"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, downloadAuthenticated } from "@/lib/api";
import { formatCompactINR } from "@/lib/utils";
import { usePageStatus } from "@/hooks/usePageStatus";
import { useAccountScopeStore } from "@/lib/account-scope-store";
import { Card } from "@/components/ui/card";
import { NumberTicker } from "@/components/ui/number-ticker";
import { EquityCurveChart } from "@/components/account/equity-curve-chart";
import { PaperPositionsTable } from "@/components/paper-trading/paper-positions-table";
import { PaperTradesTable } from "@/components/paper-trading/paper-trades-table";
import { ShadowModePanel } from "@/components/paper-trading/shadow-mode-panel";

/**
 * REL-034/013 merged (REL-082, 2026-09-04): the real, working ₹100,000 paper account -- equity,
 * capital, realized/unrealized P&L, a downloadable statement, the equity curve, the Shadow Mode
 * Go-Live precursor streak, open positions, and recent fills, all in one place. Previously split
 * across /account and /paper-trading as two separate nav tabs -- both were real slices of the
 * exact same single seeded account, each independently fetching and rendering the identical
 * CapitalSummary/PaperPositionsTable output, with a cross-link banner on each pointing at the
 * other ("Looking for Shadow Mode..."/"Looking for account equity...") that was itself a tell the
 * split created real navigation friction rather than a genuine product decision. Merged at the
 * user's explicit request after looking at both tabs side by side. /paper-trading now
 * permanently redirects here (next.config.ts).
 */
export default function AccountPage() {
  usePageStatus("Account — Live Paper Trading Ledger", false);
  const scope = useAccountScopeStore((s) => s.scope);

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
  const tradesQuery = useQuery({
    queryKey: ["paper-trades"],
    queryFn: () => api.paperTrades(),
    refetchInterval: 15_000,
  });
  const shadowQuery = useQuery({
    queryKey: ["shadow-mode-status"],
    queryFn: () => api.shadowModeStatus(),
    refetchInterval: 30_000,
  });

  const summary = summaryQuery.data;
  const realizedPositive = (summary?.realized_pnl_total ?? 0) >= 0;
  const unrealizedPositive = (summary?.unrealized_pnl_total ?? 0) >= 0;
  const availableToTrade = (summary?.cash ?? 0) - (summary?.margin_blocked ?? 0);

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      {scope === "live" && (
        <div className="rounded-xl border border-warn/20 bg-warn/[0.04] px-4 py-2.5 text-[11px] text-warn">
          You&apos;re viewing the Paper account ledger — your account scope is set to Live.{" "}
          <Link href="/" className="font-medium underline underline-offset-2">
            View real account data on the Dashboard →
          </Link>
        </div>
      )}

      <Card eyebrow="Real, Working Paper Account" title="Account Equity">
        {summaryQuery.isLoading ? (
          <div className="h-20 animate-pulse rounded-xl bg-bg" />
        ) : (
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-5">
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
            <div>
              <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
                Available to Trade
              </p>
              <p className="font-mono-tabular text-3xl font-semibold tracking-tight text-up">
                {formatCompactINR(availableToTrade)}
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

      <Card eyebrow="Rule 3 · Go-Live Precursor" title="Shadow Mode — Broker Validation Streak">
        <ShadowModePanel status={shadowQuery.data} />
      </Card>

      <Card eyebrow="Since Inception" title="Equity Curve">
        {equityCurveQuery.isLoading ? (
          <div className="h-[220px] animate-pulse rounded-xl bg-bg" />
        ) : (
          <EquityCurveChart points={equityCurveQuery.data ?? []} />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card eyebrow="Simulated Ledger" title="Positions">
          {positionsQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-bg" />
          ) : (
            <PaperPositionsTable positions={positionsQuery.data ?? []} />
          )}
        </Card>

        <Card eyebrow="Simulated Ledger" title="Recent Paper Fills">
          {tradesQuery.isLoading ? (
            <div className="h-40 animate-pulse rounded-xl bg-bg" />
          ) : (
            <PaperTradesTable trades={tradesQuery.data ?? []} />
          )}
        </Card>
      </div>

      <Card eyebrow="How this works" title="No broker paper-trading dependency">
        <p className="text-[11px] leading-relaxed text-text-faint">
          Neither Zerodha nor Upstox provides a native paper-trading mode, so this desk never
          relies on one. Every fill above is computed locally: a real live Level-2 depth quote is
          fetched from whichever broker is configured, walked by a real slippage model to produce
          a realistic fill price and partial-fill probability, and written to a local ledger —{" "}
          <code className="text-text-dim">place_order</code> is never called. Shadow Mode above
          is a separate, complementary check: it validates that a real order payload is
          syntactically correct against each broker&apos;s real API shape (a genuine sandbox call for
          Upstox, local-only validation for Zerodha, which has no sandbox at all) without ever
          risking capital either.
        </p>
      </Card>
    </main>
  );
}
