"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type OptionInstrument } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { SymbolCombobox } from "@/components/market/symbol-combobox";

function formatNumber(value: number | null, digits = 2): string {
  if (value === null) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function formatLtp(value: number | null): string {
  return value === null ? "—" : `₹${formatNumber(value)}`;
}

/** REL-077 (F&O Phase 2, part 1 of 2 -- options chain browsing; futures search+charting is part
 * 2, not yet built). Real, live broker option chain (GET /market/option-chain/{underlying},
 * REL-010 E10.4) with real, currently-listed expiries (GET /market/option-chain/{underlying}/
 * expiries, REL-030 E30.1, exposed over HTTP for the first time this release) -- both already
 * existed and worked, this is their first frontend consumer. The underlying picker reuses
 * SymbolCombobox over the real equities/indices instruments table (REL-071/076) -- an option's
 * underlying is exactly an equity or index symbol, so no separate F&O instrument sync is needed
 * for this. Live per-strike LTP/OI/IV only, sourced fresh from the broker on every query -- there
 * is no local F&O historical data (a separate, later phase, not this one). `implied_volatility`
 * is rendered as the raw number the broker/local Black-Scholes solve returns (no assumed
 * fraction-vs-percent conversion -- src/brokers/upstox_adapter.py and the local solver
 * (src/engine/options/greeks.py) don't share one documented unit convention, so guessing one
 * here risks silently misrepresenting a real number). */
export function OptionChainPanel() {
  const [underlying, setUnderlying] = useState<string | null>(null);
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);

  function handleUnderlyingSelect(symbol: string) {
    setUnderlying(symbol);
    setSelectedExpiry(null);
  }

  const expiriesQuery = useQuery({
    queryKey: ["option-expiries", underlying],
    queryFn: () => api.optionExpiries(underlying!),
    enabled: underlying !== null,
  });

  // Defaults to the nearest real expiry until the operator explicitly picks a different one --
  // derived directly from query data rather than mirrored into state via an effect, matching
  // candlestick-chart.tsx's own effectiveSymbol convention.
  const expiry = selectedExpiry ?? expiriesQuery.data?.expiries[0] ?? null;

  const chainQuery = useQuery({
    queryKey: ["option-chain", underlying, expiry],
    queryFn: () => api.optionChain(underlying!, expiry!),
    enabled: underlying !== null && expiry !== null,
  });

  const rows = useMemo(() => {
    const byStrike = new Map<number, { ce?: OptionInstrument; pe?: OptionInstrument }>();
    for (const inst of chainQuery.data?.instruments ?? []) {
      const entry = byStrike.get(inst.strike) ?? {};
      if (inst.option_type === "CE") entry.ce = inst;
      else entry.pe = inst;
      byStrike.set(inst.strike, entry);
    }
    return [...byStrike.entries()].sort(([a], [b]) => a - b);
  }, [chainQuery.data]);

  const atmStrike = useMemo(() => {
    const spot = chainQuery.data?.spot_price;
    if (spot === undefined || rows.length === 0) return null;
    return rows.reduce(
      (closest, [strike]) => (Math.abs(strike - spot) < Math.abs(closest - spot) ? strike : closest),
      rows[0][0],
    );
  }, [rows, chainQuery.data]);

  const hasNoExpiries = underlying !== null && (expiriesQuery.data?.expiries.length ?? 0) === 0;

  return (
    <Card eyebrow="Live Broker Chain" title="Options Chain" density="dense">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2.5">
        <SymbolCombobox
          value={underlying}
          onSelect={handleUnderlyingSelect}
          placeholder="Search underlying (e.g. RELIANCE, NIFTY)…"
          className="w-64"
        />
        <select
          value={expiry ?? ""}
          onChange={(e) => setSelectedExpiry(e.target.value || null)}
          disabled={!underlying || expiriesQuery.isLoading || hasNoExpiries}
          aria-label="Select expiry"
          className="rounded-md border border-card-edge bg-bg px-2 py-1.5 text-[11px] text-text disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="" disabled>
            Select expiry…
          </option>
          {expiriesQuery.data?.expiries.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>

        {chainQuery.data && (
          <span className="ml-auto text-[11px] text-text-faint">
            Spot: {formatLtp(chainQuery.data.spot_price)}
          </span>
        )}
      </div>

      {!underlying ? (
        <p className="py-8 text-center text-xs text-text-faint">
          Search and select an underlying to browse its real option chain.
        </p>
      ) : expiriesQuery.isLoading ? (
        <div className="h-40 animate-pulse rounded-xl bg-bg" />
      ) : expiriesQuery.isError ? (
        <p className="text-xs text-text-faint">
          Could not load expiries: {expiriesQuery.error.message}
        </p>
      ) : hasNoExpiries ? (
        <p className="py-8 text-center text-xs text-text-faint">
          No listed expiries found for {underlying}.
        </p>
      ) : !expiry || chainQuery.isLoading ? (
        <div className="h-40 animate-pulse rounded-xl bg-bg" />
      ) : chainQuery.isError ? (
        <p className="text-xs text-text-faint">
          Could not load the option chain: {chainQuery.error.message}
        </p>
      ) : rows.length === 0 ? (
        <p className="py-8 text-center text-xs text-text-faint">
          No option chain data for {underlying} {expiry}.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-right">CE OI</TableHead>
              <TableHead className="text-right">CE IV</TableHead>
              <TableHead className="text-right">CE LTP</TableHead>
              <TableHead className="text-center">Strike</TableHead>
              <TableHead>PE LTP</TableHead>
              <TableHead>PE IV</TableHead>
              <TableHead>PE OI</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([strike, { ce, pe }]) => (
              <TableRow key={strike} className={cn(strike === atmStrike && "bg-brand-via/5")}>
                <TableCell className="text-right text-text-dim">
                  {formatNumber(ce?.open_interest ?? null, 0)}
                </TableCell>
                <TableCell className="text-right text-text-dim">
                  {formatNumber(ce?.implied_volatility ?? null)}
                </TableCell>
                <TableCell className="text-right font-medium text-text">
                  {formatLtp(ce?.last_price ?? null)}
                </TableCell>
                <TableCell className="text-center font-medium text-text">
                  {strike.toLocaleString()}
                  {strike === atmStrike && (
                    <span className="ml-1.5 rounded-full bg-brand-via/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-brand-via">
                      ATM
                    </span>
                  )}
                </TableCell>
                <TableCell className="font-medium text-text">{formatLtp(pe?.last_price ?? null)}</TableCell>
                <TableCell className="text-text-dim">
                  {formatNumber(pe?.implied_volatility ?? null)}
                </TableCell>
                <TableCell className="text-text-dim">
                  {formatNumber(pe?.open_interest ?? null, 0)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}
