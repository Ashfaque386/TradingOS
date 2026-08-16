"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { api } from "@/lib/api";
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

type ExchangeFilter = "All" | "NSE" | "BSE";
type TypeFilter = "All" | "Equity" | "Index";

const PAGE_SIZE = 25;

function SegmentedGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] font-medium uppercase tracking-wider text-text-faint">
        {label}
      </span>
      <div
        className="inline-flex gap-0.5 rounded-lg border border-card-edge bg-bg p-0.5"
        role="group"
        aria-label={label}
      >
        {options.map((opt) => {
          const active = value === opt;
          return (
            <button
              key={opt}
              type="button"
              onClick={() => onChange(opt)}
              aria-pressed={active}
              className={cn(
                "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                active ? "bg-panel text-text shadow-card" : "text-text-faint hover:text-text-dim",
              )}
            >
              {opt}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** REL-071 (Phase 2 of the Upstox V3 + yfinance dual market-data system): browse/search the
 * real, locally-synced Upstox NSE/BSE instrument master (GET /market/instruments/search,
 * backed by src/data/ingest/instrument_sync.py + src/data/instruments.py) -- thousands of real
 * rows, unlike Data Freshness's own `symbols` list (only what's already been ingested into the
 * EOD lake). This is the first real debounced-search + server-side-paginated list in this
 * frontend; `strategy-filter-bar.tsx`'s segmented-pill filters are reused for the exchange/type
 * chips (same control vocabulary), but its filtering is client-side over an already-fetched
 * list -- instrument search can't be, so this queries the server on every filter/page change. */
export function InstrumentSearchPanel() {
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [exchange, setExchange] = useState<ExchangeFilter>("All");
  const [instrumentType, setInstrumentType] = useState<TypeFilter>("All");
  const [page, setPage] = useState(1);

  useEffect(() => {
    // A new query/filter invalidates the current page -- staying on page 4 of a narrower
    // result set would silently show an empty page rather than the real first page, so the
    // debounced commit resets it directly (not a separate effect keyed on debouncedQuery,
    // which would cascade an extra render on every filter change).
    const handle = setTimeout(() => {
      setDebouncedQuery(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(handle);
  }, [searchInput]);

  const apiInstrumentType =
    instrumentType === "Equity" ? "EQ" : instrumentType === "Index" ? "INDEX" : undefined;

  const searchQuery = useQuery({
    queryKey: ["instrument-search", debouncedQuery, exchange, instrumentType, page],
    queryFn: () =>
      api.instrumentSearch({
        q: debouncedQuery || undefined,
        exchange: exchange === "All" ? undefined : exchange,
        instrument_type: apiInstrumentType,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (prev) => prev,
  });

  const result = searchQuery.data;
  const totalPages = useMemo(
    () => (result ? Math.max(1, Math.ceil(result.total / result.page_size)) : 1),
    [result],
  );

  return (
    <Card eyebrow="Upstox Instrument Master" title="Instruments" density="dense">
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-faint" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search symbol or name…"
            aria-label="Search instruments"
            className="w-64 rounded-lg border border-card-edge bg-bg py-1.5 pl-8 pr-2.5 text-[11px] text-text placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-brand-via/40"
          />
        </div>

        <SegmentedGroup
          label="Exchange"
          options={["All", "NSE", "BSE"] as ExchangeFilter[]}
          value={exchange}
          onChange={(v) => {
            setExchange(v);
            setPage(1);
          }}
        />

        <SegmentedGroup
          label="Type"
          options={["All", "Equity", "Index"] as TypeFilter[]}
          value={instrumentType}
          onChange={(v) => {
            setInstrumentType(v);
            setPage(1);
          }}
        />

        {result && (
          <span className="ml-auto text-[11px] text-text-faint">
            {result.total.toLocaleString()} match{result.total === 1 ? "" : "es"}
          </span>
        )}
      </div>

      {searchQuery.isLoading ? (
        <div className="h-40 animate-pulse rounded-xl bg-bg" />
      ) : searchQuery.isError ? (
        <p className="text-xs text-text-faint">Could not reach the instrument search.</p>
      ) : !result || result.items.length === 0 ? (
        <p className="py-8 text-center text-xs text-text-faint">
          No instruments match this search.
        </p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Exchange</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>ISIN</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.items.map((item) => (
                <TableRow key={`${item.exchange}:${item.instrument_key}`}>
                  <TableCell className="font-medium text-text">{item.symbol}</TableCell>
                  <TableCell className="text-text-dim">{item.name}</TableCell>
                  <TableCell className="text-text-dim">{item.exchange}</TableCell>
                  <TableCell className="text-text-dim">{item.instrument_type}</TableCell>
                  <TableCell className="text-text-faint">{item.isin ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <div className="mt-3 flex items-center justify-between border-t border-card-edge pt-3">
            <span className="text-[11px] text-text-faint">
              Page {result.page} of {totalPages}
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
                className="rounded-md border border-card-edge p-1.5 text-text-dim transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                aria-label="Next page"
                className="rounded-md border border-card-edge p-1.5 text-text-dim transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}
