"use client";

import { cn } from "@/lib/utils";
import type { StrategySummary } from "@/lib/api";

/** REL-044/045: "why this strategy was proposed" -- the CEO Agent's real ResearchDirective and
 * Market Analyst's real MarketContext (src/agents/state.py) that led the pipeline to this
 * strategy, previously only transient inside AgentRun.output_state and never returned by any
 * endpoint. Full model_dump(mode="json") objects, rendered field-by-field; a strategy generated
 * before REL-044 has neither, rendered as an honest absent state. */
export function ResearchContextPanel({ strategy }: { strategy: StrategySummary }) {
  const research = strategy.research_context;
  const market = strategy.market_context;

  if (!research && !market) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        No research context captured for this strategy — generated before REL-044, or the CEO/
        Market Analyst Agent steps didn&apos;t run this thread.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
      {research && (
        <>
          <Field label="Market Regime" value={asText(research.market_regime)} />
          <Field label="Risk Tolerance" value={asText(research.risk_tolerance)} />
          <Field label="Priority Sectors" value={asTagList(research.priority_sectors)} />
          <Field label="Strategy Themes" value={asTagList(research.strategy_themes)} />
          <Field
            label="Expected Outcomes"
            value={asText(research.expected_outcomes)}
            className="sm:col-span-2"
          />
        </>
      )}
      {market && (
        <>
          <Field label="Sector Rankings" value={asTagList(market.sector_rankings)} />
          <Field label="Volatility Assessment" value={asText(market.volatility_assessment)} />
          <Field label="Macro Outlook" value={asText(market.macro_outlook)} className="sm:col-span-2" />
          {Array.isArray(market.insights) && market.insights.length > 0 && (
            <div className="rounded-lg bg-bg p-2.5 sm:col-span-2">
              <div className="text-[9px] font-medium uppercase tracking-wider text-text-faint">
                Insights
              </div>
              <ul className="mt-1 list-inside list-disc text-[11px] leading-relaxed text-text-dim">
                {(market.insights as unknown[]).map((insight, i) => (
                  <li key={i}>{String(insight)}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asTagList(value: unknown): string[] | null {
  return Array.isArray(value) && value.length > 0 ? value.map(String) : null;
}

function Field({
  label,
  value,
  className,
}: {
  label: string;
  value: string | string[] | null;
  className?: string;
}) {
  if (value === null) return null;
  return (
    <div className={cn("rounded-lg bg-bg p-2.5", className)}>
      <div className="text-[9px] font-medium uppercase tracking-wider text-text-faint">{label}</div>
      {Array.isArray(value) ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {value.map((tag) => (
            <span key={tag} className="rounded-full bg-brand-via/10 px-2 py-0.5 text-[10px] text-brand-via">
              {tag}
            </span>
          ))}
        </div>
      ) : (
        <p className="mt-0.5 text-[11px] leading-relaxed text-text-dim">{value}</p>
      )}
    </div>
  );
}
