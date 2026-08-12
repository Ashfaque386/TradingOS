"use client";

import { useState } from "react";
import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BacktestSummary } from "@/lib/api";

type ChipTone = "pass" | "fail" | "pending";

const CHIP_CLASS: Record<ChipTone, string> = {
  pass: "bg-up/10 text-up",
  fail: "bg-down/10 text-down",
  pending: "bg-bg text-text-faint",
};

const CHIP_ICON: Record<ChipTone, typeof CheckCircle2> = {
  pass: CheckCircle2,
  fail: XCircle,
  pending: CircleDashed,
};

function Chip({ tone, label }: { tone: ChipTone; label: string }) {
  const Icon = CHIP_ICON[tone];
  return (
    <span
      className={cn(
        "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider",
        CHIP_CLASS[tone],
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}

/**
 * REL-040/041: the direct fix for the reported "everything's empty" complaint -- surfaces the
 * real Evaluator/Optimization/RiskManager/Deployment agent-pipeline verdict
 * (src/api/routers/agents.py::_persist_strategy_progress) that was already computed and
 * persisted per backtest but never returned by any endpoint until REL-040. A backtest the
 * pipeline hasn't reached yet renders an explicit "Not yet evaluated" pending chip rather than
 * silently omitting the row -- matching this codebase's own honest-missing-data convention
 * (e.g. Monte Carlo P95 null vs. 0.0).
 */
export function VerdictPanel({ backtest }: { backtest: BacktestSummary }) {
  const [expanded, setExpanded] = useState(false);

  const evaluationTone: ChipTone =
    backtest.evaluation_verdict === "Pass" ? "pass" : backtest.evaluation_verdict === "Fail" ? "fail" : "pending";
  const riskTone: ChipTone =
    backtest.risk_assessment_passed === true
      ? "pass"
      : backtest.risk_assessment_passed === false
        ? "fail"
        : "pending";
  const deploymentTone: ChipTone =
    backtest.deployment_recommendation === "Approve"
      ? "pass"
      : backtest.deployment_recommendation
        ? "fail"
        : "pending";

  const hasNarrative =
    (backtest.evaluation_failure_reasons?.length ?? 0) > 0 ||
    !!backtest.risk_assessment_notes ||
    !!backtest.deployment_rationale ||
    !!backtest.optimization_best_params;

  return (
    <div className="rounded-xl border border-card-edge bg-bg/50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={evaluationTone} label={`Evaluation: ${backtest.evaluation_verdict ?? "Not yet evaluated"}`} />
        <Chip
          tone={riskTone}
          label={`Risk: ${
            backtest.risk_assessment_passed === true
              ? "Passed"
              : backtest.risk_assessment_passed === false
                ? "Failed"
                : "Not yet evaluated"
          }`}
        />
        <Chip
          tone={deploymentTone}
          label={`Deployment: ${backtest.deployment_recommendation ?? "Not yet evaluated"}`}
        />
        {backtest.optimization_robustness_score !== null && (
          <span className="ml-auto text-[10px] text-text-faint">
            Robustness score: {backtest.optimization_robustness_score.toFixed(2)}
          </span>
        )}
      </div>

      {hasNarrative && (
        <div className="mt-2">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[10px] font-medium text-brand-via hover:underline"
          >
            {expanded ? "Hide details" : "Show reasoning"}
          </button>
          {expanded && (
            <div className="mt-2 flex flex-col gap-2 text-[11px] leading-relaxed text-text-dim">
              {backtest.evaluation_failure_reasons?.length ? (
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-text-faint">
                    Evaluation failure reasons
                  </div>
                  <ul className="list-inside list-disc">
                    {backtest.evaluation_failure_reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {backtest.risk_assessment_notes && (
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-text-faint">Risk notes</div>
                  <p>{backtest.risk_assessment_notes}</p>
                </div>
              )}
              {backtest.deployment_rationale && (
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-text-faint">
                    Deployment rationale
                  </div>
                  <p>{backtest.deployment_rationale}</p>
                </div>
              )}
              {backtest.optimization_best_params && (
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-text-faint">
                    Optimized parameters
                  </div>
                  <p className="font-mono-tabular">
                    {Object.entries(backtest.optimization_best_params)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(", ")}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
