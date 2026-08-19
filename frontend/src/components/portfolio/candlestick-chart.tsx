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
import { useEnsureSymbolIngested } from "@/hooks/useEnsureSymbolIngested";
import { useThemeStore } from "@/lib/theme-store";
import { CHART_COLOR_DOWN, CHART_COLOR_UP, getChartColors } from "@/lib/chart-theme";
import { SymbolCombobox } from "@/components/market/symbol-combobox";

interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

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
  const [pendingSymbol, setPendingSymbol] = useState<string | null>(null);

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
  const mode = useThemeStore((s) => s.mode);

  // Real symbol search-and-select: a symbol not already in the local data lake is fetched on
  // demand (real Upstox V3/yfinance failover ingestion) before this chart tries to show it,
  // rather than only ever offering whatever 5-6 symbols happened to be manually ingested before.
  const { ensure, status: ingestStatus, error: ingestError } = useEnsureSymbolIngested();

  async function handleSelect(newSymbol: string) {
    setPendingSymbol(newSymbol);
    const ok = await ensure(newSymbol);
    setPendingSymbol(null);
    if (ok) setSelectedSymbol(newSymbol);
  }

  // Mount the chart once -- lightweight-charts is a vanilla-JS/Canvas library, not a React
  // component, so it's created imperatively into a ref'd container.
  useEffect(() => {
    if (!containerRef.current) return;
    const colors = getChartColors(mode);
    const chart = createChart(containerRef.current, {
      layout: { background: { color: "transparent" }, textColor: colors.textFaint },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      timeScale: { borderColor: colors.grid },
      rightPriceScale: { borderColor: colors.grid },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: CHART_COLOR_UP,
      downColor: CHART_COLOR_DOWN,
      borderVisible: false,
      wickUpColor: CHART_COLOR_UP,
      wickDownColor: CHART_COLOR_DOWN,
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
    // Intentionally mount-once (initial `mode` only) -- theme changes are applied via the
    // separate applyOptions effect below, not a remount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // React to Light/Dark toggling without tearing down and re-seeding the whole chart.
  useEffect(() => {
    if (!chartRef.current) return;
    const colors = getChartColors(mode);
    chartRef.current.applyOptions({
      layout: { textColor: colors.textFaint },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      timeScale: { borderColor: colors.grid },
      rightPriceScale: { borderColor: colors.grid },
    });
  }, [mode]);

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
        <SymbolCombobox
          value={symbol}
          onSelect={handleSelect}
          disabled={ingestStatus === "ingesting"}
          className="w-48"
        />
        <span className="text-[10px] uppercase tracking-wider text-text-faint">
          {ingestStatus === "ingesting"
            ? `Fetching real data for ${pendingSymbol}…`
            : connected
              ? "Live"
              : "Reconnecting…"}
        </span>
      </div>
      {ingestStatus === "error" && ingestError && (
        <p className="mb-2 text-[10px] text-down">{ingestError}</p>
      )}
      <div ref={containerRef} className="h-[320px] w-full" />
    </div>
  );
}
