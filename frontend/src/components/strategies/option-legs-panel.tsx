"use client";

import type { StrategyVersionSummary } from "@/lib/api";

/** REL-044/046: F&O-only -- the Options Strategy Agent's real, chain-grounded legs
 * (option_legs/option_expiry, real since REL-035) plus its own rationale for them
 * (option_rationale, new REL-044, previously discarded before it even reached graph state). */
export function OptionLegsPanel({ version }: { version: StrategyVersionSummary }) {
  if (!version.option_legs || version.option_legs.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        No real, chain-grounded option legs recorded for this version — either the options
        grounding degraded (no broker configured, no listed expiry) or this version predates
        REL-035.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      {version.option_expiry && (
        <p className="text-[11px] text-text-faint">
          Grounded against the <span className="font-mono-tabular text-text-dim">{version.option_expiry}</span>{" "}
          expiry.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[9px] uppercase tracking-wider text-text-faint">
              <th className="px-0 pb-1.5 pr-3 text-left font-normal">Symbol</th>
              <th className="px-0 pb-1.5 pr-3 text-left font-normal">Type</th>
              <th className="px-0 pb-1.5 pr-3 text-right font-normal">Strike</th>
              <th className="px-0 pb-1.5 pr-3 text-left font-normal">Side</th>
              <th className="px-0 pb-1.5 text-right font-normal">Qty</th>
            </tr>
          </thead>
          <tbody>
            {version.option_legs.map((leg, i) => (
              <tr key={i} className="border-t border-card-edge">
                <td className="px-0 py-1.5 pr-3 font-mono-tabular text-text-dim">{leg.symbol}</td>
                <td className="px-0 py-1.5 pr-3 text-text-dim">{leg.option_type}</td>
                <td className="px-0 py-1.5 pr-3 text-right font-mono-tabular text-text-faint">
                  {leg.strike}
                </td>
                <td className="px-0 py-1.5 pr-3 capitalize text-text-dim">{leg.side}</td>
                <td className="px-0 py-1.5 text-right font-mono-tabular text-text-faint">{leg.quantity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {version.option_rationale && (
        <div className="rounded-lg bg-bg p-2.5">
          <div className="text-[9px] font-medium uppercase tracking-wider text-text-faint">
            Agent Rationale
          </div>
          <p className="mt-0.5 text-[11px] leading-relaxed text-text-dim">{version.option_rationale}</p>
        </div>
      )}
    </div>
  );
}
