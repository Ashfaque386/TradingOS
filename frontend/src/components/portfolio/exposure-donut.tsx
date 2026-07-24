"use client";

import ReactECharts from "echarts-for-react";
import { useState } from "react";
import { cn, formatCompactINR } from "@/lib/utils";
import type { SymbolExposure } from "@/lib/api";

const PALETTE = [
  "#22d3ee",
  "#a78bfa",
  "#34d399",
  "#fbbf24",
  "#fb7185",
  "#60a5fa",
  "#f472b6",
  "#4ade80",
];

type Tab = "symbol" | "sector" | "strategy";

export function ExposureDonut({
  bySymbol,
  grossExposure,
  sectorAvailable,
  strategyAvailable,
}: {
  bySymbol: SymbolExposure[];
  grossExposure: number;
  sectorAvailable: boolean;
  strategyAvailable: boolean;
}) {
  const [tab, setTab] = useState<Tab>("symbol");

  const tabs: { key: Tab; label: string }[] = [
    { key: "symbol", label: "By Symbol" },
    { key: "sector", label: "By Sector" },
    { key: "strategy", label: "By Strategy" },
  ];

  return (
    <div>
      <div className="mb-4 flex gap-1 rounded-lg bg-black/30 p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
              tab === t.key
                ? "bg-white/10 text-zinc-100"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "symbol" && <SymbolDonut positions={bySymbol} gross={grossExposure} />}
      {tab === "sector" && !sectorAvailable && (
        <UnavailableState message="Sector-constituent mapping not yet ingested (NseSectorDataSkill is a documented stub)." />
      )}
      {tab === "strategy" && !strategyAvailable && (
        <UnavailableState message="Position → strategy linkage isn't persisted yet — live positions aren't tagged with the strategy that opened them." />
      )}
    </div>
  );
}

function SymbolDonut({ positions, gross }: { positions: SymbolExposure[]; gross: number }) {
  if (positions.length === 0) {
    return (
      <UnavailableState message="No open positions right now — the donut fills in as soon as positions are live." />
    );
  }

  const option = {
    tooltip: {
      trigger: "item",
      backgroundColor: "rgba(24,24,27,0.95)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#f4f4f5", fontFamily: "var(--font-sans)" },
      formatter: (p: { name: string; value: number; percent: number }) =>
        `${p.name}<br/>${formatCompactINR(p.value)} · ${p.percent}%`,
    },
    series: [
      {
        type: "pie",
        radius: ["58%", "88%"],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: "#09090b", borderWidth: 3 },
        label: { show: false },
        labelLine: { show: false },
        data: positions.map((p, i) => ({
          name: p.symbol,
          value: Number(p.market_value.toFixed(2)),
          itemStyle: { color: PALETTE[i % PALETTE.length] },
        })),
      },
    ],
  };

  return (
    <div className="relative">
      <ReactECharts option={option} style={{ height: 220 }} opts={{ renderer: "svg" }} />
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">Gross</div>
        <div className="font-mono-tabular text-lg font-semibold text-zinc-100">
          {formatCompactINR(gross)}
        </div>
      </div>
    </div>
  );
}

function UnavailableState({ message }: { message: string }) {
  return (
    <div className="flex h-[220px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 px-6 text-center">
      <div className="h-2 w-2 rounded-full bg-amber-400/70" />
      <p className="max-w-[220px] text-xs leading-relaxed text-zinc-500">{message}</p>
    </div>
  );
}
