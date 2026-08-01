"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, ShieldAlert, XCircle } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import type { RiskLimitChangePayload, RiskLimitChangeRequest } from "@/lib/api";

const QUERY_KEY_CURRENT = ["risk-limits-current"];
const QUERY_KEY_PENDING = ["risk-limits-change-requests", "PENDING"];

/** REL-017 E17.1: surfaces src/api/routers/risk_limits.py's real dual-control stage/confirm/
 * reject workflow -- previously fully built and tested with zero UI anywhere. */
export function RiskLimitsPanel() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [staging, setStaging] = useState(false);

  const currentQuery = useQuery({ queryKey: QUERY_KEY_CURRENT, queryFn: api.currentRiskLimit });
  const pendingQuery = useQuery({
    queryKey: QUERY_KEY_PENDING,
    queryFn: () => api.riskLimitChangeRequests("PENDING"),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: QUERY_KEY_CURRENT });
    queryClient.invalidateQueries({ queryKey: QUERY_KEY_PENDING });
  };

  const confirm = useMutation({
    mutationFn: (requestId: string) => api.confirmRiskLimitChange(requestId),
    onSuccess: invalidate,
  });
  const reject = useMutation({
    mutationFn: ({ requestId, reason }: { requestId: string; reason: string }) =>
      api.rejectRiskLimitChange(requestId, reason),
    onSuccess: invalidate,
  });

  const current = currentQuery.data;
  const pending = pendingQuery.data ?? [];

  return (
    <div className="space-y-4">
      {currentQuery.isLoading ? (
        <div className="h-16 animate-pulse rounded-xl bg-white/5" />
      ) : current ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <LimitStat label="Max daily loss" value={`₹${current.max_daily_loss.toLocaleString()}`} />
          <LimitStat
            label="Max position size"
            value={current.max_position_size_pct !== null ? `${current.max_position_size_pct}%` : "—"}
          />
          <LimitStat
            label="Max sector exposure"
            value={current.max_sector_exposure_pct !== null ? `${current.max_sector_exposure_pct}%` : "—"}
          />
          <LimitStat
            label="Max drawdown"
            value={current.max_drawdown_pct !== null ? `${current.max_drawdown_pct}%` : "—"}
          />
        </div>
      ) : (
        <p className="text-xs text-zinc-500">
          No risk limit has ever been confirmed for this scope yet.
        </p>
      )}

      {pending.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
            Pending change requests
          </p>
          {pending.map((request) => (
            <PendingChangeRow
              key={request.id}
              request={request}
              isOwnStage={request.staged_by_user_id === user?.id}
              onConfirm={() => confirm.mutate(request.id)}
              onReject={(reason) => reject.mutate({ requestId: request.id, reason })}
              confirming={confirm.isPending}
              rejecting={reject.isPending}
            />
          ))}
        </div>
      )}

      <Gated permission="manageRiskLimits">
        {staging ? (
          <StageChangeForm
            onDone={() => {
              setStaging(false);
              queryClient.invalidateQueries({ queryKey: QUERY_KEY_PENDING });
            }}
          />
        ) : (
          <button
            onClick={() => setStaging(true)}
            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-white/10 py-2.5 text-xs font-medium text-zinc-500 transition hover:border-white/20 hover:text-zinc-300"
          >
            <ShieldAlert className="h-3.5 w-3.5" /> Stage a risk limit change
          </button>
        )}
      </Gated>
    </div>
  );
}

function LimitStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/5 bg-black/20 p-3">
      <p className="font-mono-tabular text-sm text-zinc-100">{value}</p>
      <p className="mt-1 text-[10px] uppercase tracking-wider text-zinc-600">{label}</p>
    </div>
  );
}

function PendingChangeRow({
  request,
  isOwnStage,
  onConfirm,
  onReject,
  confirming,
  rejecting,
}: {
  request: RiskLimitChangeRequest;
  isOwnStage: boolean;
  onConfirm: () => void;
  onReject: (reason: string) => void;
  confirming: boolean;
  rejecting: boolean;
}) {
  return (
    <div className="rounded-xl border border-amber-400/20 bg-amber-400/[0.04] p-3.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Clock className="h-3.5 w-3.5 text-amber-300" />
          <span className="font-mono-tabular text-xs text-zinc-200">
            {request.scope_type}: max daily loss → ₹{request.max_daily_loss.toLocaleString()}
          </span>
        </div>
        <Gated permission="manageRiskLimits">
          <div className="flex gap-1.5">
            <button
              onClick={onConfirm}
              disabled={isOwnStage || confirming}
              title={isOwnStage ? "A second, distinct privileged user must confirm (SEC-013)" : ""}
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium transition",
                isOwnStage
                  ? "cursor-not-allowed bg-white/5 text-zinc-600"
                  : "bg-emerald-400/15 text-emerald-300 hover:bg-emerald-400/25",
              )}
            >
              <CheckCircle2 className="h-3 w-3" /> Confirm
            </button>
            <button
              onClick={() => onReject("Rejected from Settings UI")}
              disabled={rejecting}
              className="flex items-center gap-1 rounded-md bg-rose-400/15 px-2 py-1 text-[10px] font-medium text-rose-300 transition hover:bg-rose-400/25"
            >
              <XCircle className="h-3 w-3" /> Reject
            </button>
          </div>
        </Gated>
      </div>
      {isOwnStage && (
        <p className="mt-2 text-[10px] text-amber-400/70">
          You staged this change — a different SystemAdministrator or RiskManager must confirm it.
        </p>
      )}
    </div>
  );
}

function StageChangeForm({ onDone }: { onDone: () => void }) {
  const [maxDailyLoss, setMaxDailyLoss] = useState("");
  const [maxDrawdownPct, setMaxDrawdownPct] = useState("");

  const stage = useMutation({
    mutationFn: (payload: RiskLimitChangePayload) => api.stageRiskLimitChange(payload),
    onSuccess: onDone,
  });

  const submit = () => {
    const parsedLoss = Number(maxDailyLoss);
    if (!maxDailyLoss.trim() || Number.isNaN(parsedLoss)) return;
    stage.mutate({
      scope_type: "Global",
      max_daily_loss: parsedLoss,
      max_drawdown_pct: maxDrawdownPct.trim() ? Number(maxDrawdownPct) : undefined,
      effective_from: new Date().toISOString(),
    });
  };

  return (
    <div className="rounded-xl border border-cyan-400/20 bg-cyan-400/[0.03] p-3.5">
      <div className="flex flex-wrap gap-2">
        <input
          value={maxDailyLoss}
          onChange={(e) => setMaxDailyLoss(e.target.value)}
          placeholder="Max daily loss (₹)"
          inputMode="decimal"
          className="min-w-[160px] flex-1 rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600"
        />
        <input
          value={maxDrawdownPct}
          onChange={(e) => setMaxDrawdownPct(e.target.value)}
          placeholder="Max drawdown % (optional)"
          inputMode="decimal"
          className="min-w-[160px] flex-1 rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600"
        />
      </div>
      <p className="mt-2 text-[10px] text-zinc-500">
        Scope: Global, effective immediately once confirmed. Requires a second, distinct
        SystemAdministrator or RiskManager to confirm before it takes effect (SEC-013).
      </p>
      <div className="mt-3 flex gap-2">
        <button
          onClick={onDone}
          className="flex-1 rounded-lg border border-white/10 py-1.5 text-[11px] text-zinc-400 hover:bg-white/5"
        >
          Cancel
        </button>
        <button
          onClick={submit}
          disabled={!maxDailyLoss.trim() || stage.isPending}
          className="flex-1 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-500 py-1.5 text-[11px] font-semibold text-black transition hover:brightness-110 disabled:opacity-40"
        >
          {stage.isPending ? "Staging…" : "Stage change"}
        </button>
      </div>
      {stage.isError && (
        <p className="mt-2 text-[10px] text-rose-400">Failed to stage change. Check the values.</p>
      )}
    </div>
  );
}
