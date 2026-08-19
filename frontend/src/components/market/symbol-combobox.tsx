"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "@/lib/api";

const PAGE_SIZE = 8;
const DEBOUNCE_MS = 300;

/** Real symbol search-and-select across the full, locally-synced NSE/BSE instrument universe
 * (2,776 real equities + indices, `GET /market/instruments/search`, REL-071) -- not just
 * whichever handful of symbols happen to already be in the local data lake. No `instrument_type`
 * filter is applied, so this returns whatever's actually populated in the `instruments` table
 * today (equities + indices) and will start returning F&O rows for free once that's synced too,
 * with no change needed here. Same 300ms-debounce pattern as
 * `market-analysis/instrument-search-panel.tsx`. Selecting a row only reports the symbol back to
 * the caller -- it does not itself ensure the symbol's data is ingested (see
 * `useEnsureSymbolIngested`, meant to be called from `onSelect`). */
export function SymbolCombobox({
  value,
  onSelect,
  disabled,
  className,
  placeholder = "Search symbol or name…",
}: {
  value: string | null;
  onSelect: (symbol: string) => void;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
}) {
  // `isEditing` is the source of truth for which value the input displays -- while editing, it
  // shows the user's own typed text (`inputValue`); otherwise it derives straight from the
  // controlled `value` prop during render. This avoids a "sync a prop into state via an effect"
  // pattern entirely (react-hooks' set-state-in-effect lint rule), not just papering over it.
  const [inputValue, setInputValue] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const displayValue = isEditing ? inputValue : (value ?? "");

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(inputValue.trim()), DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [inputValue]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setIsEditing(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const searchQuery = useQuery({
    queryKey: ["instrument-search-combobox", debouncedQuery],
    queryFn: () => api.instrumentSearch({ q: debouncedQuery, page: 1, page_size: PAGE_SIZE }),
    enabled: isOpen && debouncedQuery.length >= 1,
  });

  const results = searchQuery.data?.items ?? [];

  function handleSelect(symbol: string) {
    setIsOpen(false);
    setIsEditing(false);
    onSelect(symbol);
  }

  return (
    <div ref={containerRef} className={`relative ${className ?? ""}`}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-text-faint" />
        <input
          type="text"
          value={displayValue}
          disabled={disabled}
          onChange={(e) => {
            setIsEditing(true);
            setInputValue(e.target.value);
            setIsOpen(true);
          }}
          onFocus={(e) => {
            setIsEditing(true);
            setInputValue(value ?? "");
            setIsOpen(true);
            e.target.select();
          }}
          placeholder={placeholder}
          aria-label="Search symbol or name"
          className="w-full rounded-md border border-card-edge bg-bg py-1 pl-6 pr-2 text-[10px] text-text placeholder:text-text-faint disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      {isOpen && debouncedQuery.length >= 1 && (
        <div className="absolute left-0 top-full z-10 mt-1 w-64 rounded-md border border-card-edge bg-panel shadow-card">
          {searchQuery.isLoading ? (
            <p className="p-2 text-[10px] text-text-faint">Searching…</p>
          ) : results.length === 0 ? (
            <p className="p-2 text-[10px] text-text-faint">No instruments match this search.</p>
          ) : (
            <ul>
              {results.map((item) => (
                <li key={`${item.exchange}:${item.instrument_key}`}>
                  <button
                    type="button"
                    onClick={() => handleSelect(item.symbol)}
                    className="flex w-full flex-col items-start gap-0.5 px-2.5 py-1.5 text-left hover:bg-bg"
                  >
                    <span className="text-[11px] font-medium text-text">{item.symbol}</span>
                    <span className="text-[10px] text-text-faint">
                      {item.name} ({item.exchange})
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
