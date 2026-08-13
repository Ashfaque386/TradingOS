"use client";

import { cn } from "@/lib/utils";
import type { StrategySummary } from "@/lib/api";

/** REL-044/045: the direct fix for "No hypothesis recorded." being the entire strategy-detail
 * surface -- renders the rest of the Strategy Generator Agent's real StrategyLogic output
 * (entry/exit conditions, stop-loss, take-profit, position sizing, confidence score), computed
 * by the LLM on every run since Phase 2 but only ever partially persisted until REL-044. A
 * strategy generated before that migration has none of these fields -- rendered as an honest
 * "generated before this feature shipped" state, never a broken-looking empty layout. */
export function StrategyLogicPanel({ strategy }: { strategy: StrategySummary }) {
  const hasLogic =
    strategy.entry_conditions !== null ||
    strategy.exit_conditions !== null ||
    strategy.stop_loss !== null ||
    strategy.take_profit !== null ||
    strategy.position_sizing !== null ||
    strategy.confidence_score !== null;

  if (!hasLogic) {
    return (
      <p className="text-[11px] leading-relaxed text-text-faint">
        This strategy was generated before real trading-logic capture shipped (REL-044) — only
        its hypothesis was persisted at the time. Regenerate it to see the full entry/exit/risk
        logic here.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {strategy.confidence_score !== null && <ConfidenceMeter score={strategy.confidence_score} />}
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        <LogicField label="Entry Conditions" value={strategy.entry_conditions} />
        <LogicField label="Exit Conditions" value={strategy.exit_conditions} />
        <LogicField label="Stop Loss" value={strategy.stop_loss} />
        <LogicField label="Take Profit" value={strategy.take_profit} />
        <LogicField label="Position Sizing" value={strategy.position_sizing} className="sm:col-span-2" />
      </div>
    </div>
  );
}

function LogicField({
  label,
  value,
  className,
}: {
  label: string;
  value: string | null;
  className?: string;
}) {
  if (value === null) return null;
  return (
    <div className={cn("rounded-lg bg-bg p-2.5", className)}>
      <div className="text-[9px] font-medium uppercase tracking-wider text-text-faint">{label}</div>
      <p className="mt-0.5 text-[11px] leading-relaxed text-text-dim">{value}</p>
    </div>
  );
}

/** Direction/Magnitude/Confidence-style insight framing (the standard vocabulary premium
 * quant platforms use to surface an AI's own conviction) -- the LLM's real confidence_score
 * gets a first-class visual treatment here rather than sitting as a buried number. */
function ConfidenceMeter({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tone = score >= 0.7 ? "up" : score >= 0.4 ? "warn" : "down";
  const toneClass = { up: "text-up", warn: "text-warn", down: "text-down" }[tone];
  const barClass = { up: "bg-up", warn: "bg-warn", down: "bg-down" }[tone];
  return (
    <div className="rounded-lg bg-bg p-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[9px] font-medium uppercase tracking-wider text-text-faint">
          Agent Confidence
        </span>
        <span className={cn("font-mono-tabular text-xs font-semibold", toneClass)}>{pct}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-card-edge">
        <div className={cn("h-full rounded-full", barClass)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
