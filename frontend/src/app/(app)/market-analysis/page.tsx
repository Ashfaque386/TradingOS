"use client";

import { usePageStatus } from "@/hooks/usePageStatus";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MarketPulseCard } from "@/components/market-analysis/market-pulse-card";
import { SectorPerformanceChart } from "@/components/market-analysis/sector-performance-chart";
import { TechnicalAnalysisChart } from "@/components/market-analysis/technical-analysis-chart";
import { DataFreshnessStrip } from "@/components/market-analysis/data-freshness-strip";
import { InstrumentSearchPanel } from "@/components/market-analysis/instrument-search-panel";
import { ProviderStatusPanel } from "@/components/market-analysis/provider-status-panel";
import { OptionChainPanel } from "@/components/market-analysis/option-chain-panel";

/** REL-067 (Phase 1 of 3 -- Market Analysis): 3 real aspects of current market state, tabbed
 * rather than 3 separate nav entries -- switching between genuinely different data views, unlike
 * Portfolio & Risk's earlier tab mistake (that one hid simultaneously-relevant account data).
 * Every figure here traces to a real endpoint: GET /market/pulse (India VIX + NSE sector-index
 * day-change, the same real data the Market Analyst Agent's own skills already fetch),
 * GET /market/ohlcv/{symbol}/indicators (previously dead-code technical-indicator math, wired to
 * a real endpoint for the first time), and GET /market/datalake/status (existed since REL-010,
 * its first frontend consumer).
 * REL-071 (Phase 2 of the Upstox V3 + yfinance dual market-data system): 4th tab, "Instruments"
 * -- browse/search the real, locally-synced Upstox NSE/BSE instrument master, a genuinely
 * separate concern from the other 3 tabs' already-ingested-data views.
 * REL-073 (Phase 4, final): the Data Freshness tab gains a Provider Status panel alongside the
 * existing lake-freshness strip -- both answer the same "is our data infrastructure healthy"
 * question, one for the Parquet lake, the other for the upstream Upstox V3/yfinance providers
 * themselves, so grouped together rather than a 5th tab.
 * REL-077 (F&O Phase 2, part 1 of 2): 5th tab, "Options Chain" -- a real, live per-strike broker
 * option chain (GET /market/option-chain/{underlying}, real since REL-010 but never wired into
 * any UI until now), a genuinely different concern from the other 4 tabs' already-ingested-data
 * views since it's a live broker call on every query, not a locally-stored one. */
export default function MarketAnalysisPage() {
  usePageStatus("Market Analysis", false);

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <Tabs defaultValue="pulse">
        <TabsList>
          <TabsTrigger value="pulse">Market Pulse</TabsTrigger>
          <TabsTrigger value="technical">Technical Analysis</TabsTrigger>
          <TabsTrigger value="freshness">Data Freshness</TabsTrigger>
          <TabsTrigger value="instruments">Instruments</TabsTrigger>
          <TabsTrigger value="options">Options Chain</TabsTrigger>
        </TabsList>

        <TabsContent value="pulse" className="mt-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <MarketPulseCard />
            <SectorPerformanceChart />
          </div>
        </TabsContent>

        <TabsContent value="technical" className="mt-4">
          <TechnicalAnalysisChart />
        </TabsContent>

        <TabsContent value="freshness" className="mt-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <DataFreshnessStrip />
            <ProviderStatusPanel />
          </div>
        </TabsContent>

        <TabsContent value="instruments" className="mt-4">
          <InstrumentSearchPanel />
        </TabsContent>

        <TabsContent value="options" className="mt-4">
          <OptionChainPanel />
        </TabsContent>
      </Tabs>
    </main>
  );
}
