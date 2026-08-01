"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { api } from "@/lib/api";
import { useMarketStream } from "@/hooks/useMarketStream";

interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

// Known Tailwind default hex values already used elsewhere in this app (kill-switch-button.tsx's
// rose/emerald palette) -- lightweight-charts needs literal color strings in its options object,
// not CSS custom-property references.
const COLOR_ZINC_500 = "#71717a";
const COLOR_GRID = "rgba(255,255,255,0.06)";
const COLOR_UP = "#34d399";
const COLOR_DOWN = "#fb7185";

/** REL-011 E11.1: real OHLCV candlestick chart via TradingView Lightweight Charts -- seeds from
 * real historical daily bars (GET /market/ohlcv/{symbol}, REL-010 E10.8a), then aggregates real
 * live ticks (WS /stream/market/{symbol}) into the current still-forming daily bar. The "frame-
 * rate budget" applies to update frequency (useMarketStream's own rAF throttling), not to
 * fetching a new bar per tick. */
export function CandlestickChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const currentBarRef = useRef<Bar | null>(null);

  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  const symbolsQuery = useQuery({ queryKey: ["market-symbols"], queryFn: api.symbols });
  // Defaults to the first real ingested symbol until the operator explicitly picks a different
  // one -- derived directly from query data rather than mirrored into state via an effect,
  // matching app/agents/page.tsx's effectiveRunId convention.
  const symbol = selectedSymbol ?? symbolsQuery.data?.[0] ?? null;

  const ohlcvQuery = useQuery({
    queryKey: ["ohlcv", symbol],
    queryFn: () => api.ohlcv(symbol!),
    enabled: !!symbol,
  });

  const { tick, connected } = useMarketStream(symbol);

  // Mount the chart once -- lightweight-charts is a vanilla-JS/Canvas library, not a React
  // component, so it's created imperatively into a ref'd container.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: "transparent" }, textColor: COLOR_ZINC_500 },
      grid: { vertLines: { color: COLOR_GRID }, horzLines: { color: COLOR_GRID } },
      timeScale: { borderColor: COLOR_GRID },
      rightPriceScale: { borderColor: COLOR_GRID },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: COLOR_UP,
      downColor: COLOR_DOWN,
      borderVisible: false,
      wickUpColor: COLOR_UP,
      wickDownColor: COLOR_DOWN,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) chart.resize(entry.contentRect.width, entry.contentRect.height);
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Seed real historical bars whenever the symbol (or its fetched data) changes.
  useEffect(() => {
    if (!seriesRef.current || !ohlcvQuery.data) return;
    const bars: Bar[] = ohlcvQuery.data.map((b) => ({
      time: b.date,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    seriesRef.current.setData(bars);
    currentBarRef.current = bars.length > 0 ? { ...bars[bars.length - 1] } : null;
  }, [ohlcvQuery.data]);

  // Aggregate real live ticks into the current still-forming daily bar.
  useEffect(() => {
    if (!tick || !seriesRef.current) return;
    const tickDate = tick.ts ? tick.ts.slice(0, 10) : new Date().toISOString().slice(0, 10);
    const current = currentBarRef.current;
    const bar: Bar =
      current && current.time === tickDate
        ? {
            time: tickDate,
            open: current.open,
            high: Math.max(current.high, tick.ltp),
            low: Math.min(current.low, tick.ltp),
            close: tick.ltp,
          }
        : { time: tickDate, open: tick.ltp, high: tick.ltp, low: tick.ltp, close: tick.ltp };
    currentBarRef.current = bar;
    seriesRef.current.update(bar);
  }, [tick]);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <select
          value={symbol ?? ""}
          onChange={(e) => setSelectedSymbol(e.target.value)}
          className="rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-zinc-200"
        >
          {(symbolsQuery.data ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <span className="text-[10px] uppercase tracking-wider text-zinc-600">
          {connected ? "Live" : "Reconnecting…"}
        </span>
      </div>
      <div ref={containerRef} className="h-[320px] w-full" />
    </div>
  );
}
