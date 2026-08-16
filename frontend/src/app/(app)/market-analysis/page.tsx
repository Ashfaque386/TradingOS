"use client";

import { usePageStatus } from "@/hooks/usePageStatus";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MarketPulseCard } from "@/components/market-analysis/market-pulse-card";
import { SectorPerformanceChart } from "@/components/market-analysis/sector-performance-chart";
import { TechnicalAnalysisChart } from "@/components/market-analysis/technical-analysis-chart";
import { DataFreshnessStrip } from "@/components/market-analysis/data-freshness-strip";
import { InstrumentSearchPanel } from "@/components/market-analysis/instrument-search-panel";

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
 * separate concern from the other 3 tabs' already-ingested-data views. */
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
          <DataFreshnessStrip />
        </TabsContent>

        <TabsContent value="instruments" className="mt-4">
          <InstrumentSearchPanel />
        </TabsContent>
      </Tabs>
    </main>
  );
}
