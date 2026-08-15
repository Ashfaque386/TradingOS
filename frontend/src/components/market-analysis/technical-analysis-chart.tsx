"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from "lightweight-charts";
import { api } from "@/lib/api";
import { useThemeStore } from "@/lib/theme-store";
import { CHART_COLOR_DOWN, CHART_COLOR_UP, getChartColors } from "@/lib/chart-theme";
import { Card } from "@/components/ui/card";

const SMA_COLOR = "#60a5fa";
const EMA_COLOR = "#c94bff";
const BAND_COLOR = "rgba(96, 165, 250, 0.5)";

/** REL-067: real technical indicators (src/data/features/indicators.py, wired to
 * GET /market/ohlcv/{symbol}/indicators for the first time this release) overlaid on the real
 * candlestick price series (GET /market/ohlcv/{symbol}, the same source
 * components/portfolio/candlestick-chart.tsx already uses) plus RSI-14 and MACD as separate
 * synced sub-charts below. Deliberately a new component, not a modification of the existing
 * candlestick-chart.tsx used on Portfolio & Risk -- a different use case, keeps that
 * already-working component untouched. */
export function TechnicalAnalysisChart() {
  const priceContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);

  const priceChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);

  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const smaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbUpperSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdLineSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const symbolsQuery = useQuery({ queryKey: ["market-symbols"], queryFn: api.symbols });
  const symbol = selectedSymbol ?? symbolsQuery.data?.[0] ?? null;

  const ohlcvQuery = useQuery({
    queryKey: ["ohlcv", symbol],
    queryFn: () => api.ohlcv(symbol!),
    enabled: !!symbol,
  });
  const indicatorsQuery = useQuery({
    queryKey: ["ohlcv-indicators", symbol],
    queryFn: () => api.ohlcvIndicators(symbol!),
    enabled: !!symbol,
  });

  const mode = useThemeStore((s) => s.mode);

  // Mount the price chart + 2 sub-charts once.
  useEffect(() => {
    if (!priceContainerRef.current || !rsiContainerRef.current || !macdContainerRef.current) {
      return;
    }
    const colors = getChartColors(mode);
    const commonOptions = {
      layout: { background: { color: "transparent" }, textColor: colors.textFaint },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      timeScale: { borderColor: colors.grid },
      rightPriceScale: { borderColor: colors.grid },
    };

    const priceChart = createChart(priceContainerRef.current, commonOptions);
    const candleSeries = priceChart.addSeries(CandlestickSeries, {
      upColor: CHART_COLOR_UP,
      downColor: CHART_COLOR_DOWN,
      borderVisible: false,
      wickUpColor: CHART_COLOR_UP,
      wickDownColor: CHART_COLOR_DOWN,
    });
    const smaSeries = priceChart.addSeries(LineSeries, {
      color: SMA_COLOR,
      lineWidth: 1,
      title: "SMA 20",
    });
    const emaSeries = priceChart.addSeries(LineSeries, {
      color: EMA_COLOR,
      lineWidth: 1,
      title: "EMA 20",
    });
    const bbUpperSeries = priceChart.addSeries(LineSeries, {
      color: BAND_COLOR,
      lineWidth: 1,
      lineStyle: 2,
      title: "BB Upper",
    });
    const bbLowerSeries = priceChart.addSeries(LineSeries, {
      color: BAND_COLOR,
      lineWidth: 1,
      lineStyle: 2,
      title: "BB Lower",
    });

    const rsiChart = createChart(rsiContainerRef.current, commonOptions);
    const rsiSeries = rsiChart.addSeries(LineSeries, { color: EMA_COLOR, lineWidth: 2 });
    rsiSeries.createPriceLine({
      price: 70,
      color: CHART_COLOR_DOWN,
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "70",
    });
    rsiSeries.createPriceLine({
      price: 30,
      color: CHART_COLOR_UP,
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "30",
    });

    const macdChart = createChart(macdContainerRef.current, commonOptions);
    const macdHistSeries = macdChart.addSeries(HistogramSeries, {});
    const macdLineSeries = macdChart.addSeries(LineSeries, { color: SMA_COLOR, lineWidth: 1 });
    const macdSignalSeries = macdChart.addSeries(LineSeries, { color: EMA_COLOR, lineWidth: 1 });

    priceChartRef.current = priceChart;
    rsiChartRef.current = rsiChart;
    macdChartRef.current = macdChart;
    candleSeriesRef.current = candleSeries;
    smaSeriesRef.current = smaSeries;
    emaSeriesRef.current = emaSeries;
    bbUpperSeriesRef.current = bbUpperSeries;
    bbLowerSeriesRef.current = bbLowerSeries;
    rsiSeriesRef.current = rsiSeries;
    macdLineSeriesRef.current = macdLineSeries;
    macdSignalSeriesRef.current = macdSignalSeries;
    macdHistSeriesRef.current = macdHistSeries;

    // One-directional sync (price chart is the master) -- avoids a feedback loop between 3
    // charts subscribing to each other's range-change events.
    priceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range) return;
      rsiChart.timeScale().setVisibleLogicalRange(range);
      macdChart.timeScale().setVisibleLogicalRange(range);
    });

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.target === priceContainerRef.current) {
          priceChart.resize(entry.contentRect.width, entry.contentRect.height);
        }
        if (entry.target === rsiContainerRef.current) {
          rsiChart.resize(entry.contentRect.width, entry.contentRect.height);
        }
        if (entry.target === macdContainerRef.current) {
          macdChart.resize(entry.contentRect.width, entry.contentRect.height);
        }
      }
    });
    resizeObserver.observe(priceContainerRef.current);
    resizeObserver.observe(rsiContainerRef.current);
    resizeObserver.observe(macdContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      priceChart.remove();
      rsiChart.remove();
      macdChart.remove();
      priceChartRef.current = null;
      rsiChartRef.current = null;
      macdChartRef.current = null;
    };
    // Intentionally mount-once (initial `mode` only) -- theme changes are applied via the
    // separate applyOptions effect below, not a remount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // React to Light/Dark toggling without tearing down and re-seeding all 3 charts.
  useEffect(() => {
    const colors = getChartColors(mode);
    const options = {
      layout: { textColor: colors.textFaint },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      timeScale: { borderColor: colors.grid },
      rightPriceScale: { borderColor: colors.grid },
    };
    priceChartRef.current?.applyOptions(options);
    rsiChartRef.current?.applyOptions(options);
    macdChartRef.current?.applyOptions(options);
  }, [mode]);

  // Seed real OHLCV bars into the candlestick series.
  useEffect(() => {
    if (!candleSeriesRef.current || !ohlcvQuery.data) return;
    candleSeriesRef.current.setData(
      ohlcvQuery.data.map((b) => ({
        time: b.date,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );
    priceChartRef.current?.timeScale().fitContent();
  }, [ohlcvQuery.data]);

  // Seed real indicator series -- a `null` field (not enough history yet for that rolling
  // window) is simply omitted from that series' data, leaving an honest gap rather than a
  // fabricated early value.
  useEffect(() => {
    if (!indicatorsQuery.data) return;
    if (
      !smaSeriesRef.current ||
      !emaSeriesRef.current ||
      !bbUpperSeriesRef.current ||
      !bbLowerSeriesRef.current ||
      !rsiSeriesRef.current ||
      !macdLineSeriesRef.current ||
      !macdSignalSeriesRef.current ||
      !macdHistSeriesRef.current
    ) {
      return;
    }
    const points = indicatorsQuery.data;

    const line = (key: "sma_20" | "ema_20" | "bb_upper" | "bb_lower" | "rsi_14" | "macd_line" | "macd_signal") =>
      points
        .filter((p) => p[key] !== null)
        .map((p) => ({ time: p.date, value: p[key] as number }));

    smaSeriesRef.current.setData(line("sma_20"));
    emaSeriesRef.current.setData(line("ema_20"));
    bbUpperSeriesRef.current.setData(line("bb_upper"));
    bbLowerSeriesRef.current.setData(line("bb_lower"));
    rsiSeriesRef.current.setData(line("rsi_14"));
    macdLineSeriesRef.current.setData(line("macd_line"));
    macdSignalSeriesRef.current.setData(line("macd_signal"));
    macdHistSeriesRef.current.setData(
      points
        .filter((p) => p.macd_histogram !== null)
        .map((p) => ({
          time: p.date,
          value: p.macd_histogram as number,
          color: (p.macd_histogram as number) >= 0 ? CHART_COLOR_UP : CHART_COLOR_DOWN,
        })),
    );
  }, [indicatorsQuery.data]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <select
          value={symbol ?? ""}
          onChange={(e) => setSelectedSymbol(e.target.value)}
          className="rounded-md border border-card-edge bg-panel px-2 py-1.5 text-xs text-text"
        >
          {(symbolsQuery.data ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <div className="flex items-center gap-3 text-[10px] text-text-faint">
          <Legend color={SMA_COLOR} label="SMA 20" />
          <Legend color={EMA_COLOR} label="EMA 20" />
          <Legend color={BAND_COLOR} label="Bollinger" />
        </div>
      </div>

      <Card density="dense">
        <div ref={priceContainerRef} className="h-[320px] w-full" />
      </Card>
      <Card eyebrow="Momentum" title="RSI (14)" density="dense">
        <div ref={rsiContainerRef} className="h-[120px] w-full" />
      </Card>
      <Card eyebrow="Trend" title="MACD (12, 26, 9)" density="dense">
        <div ref={macdContainerRef} className="h-[120px] w-full" />
      </Card>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
