"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type StrategySuggestion, type StrategyVersionSummary } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSuggestionReviewJob } from "@/hooks/useSuggestionReviewJob";
import { Button } from "@/components/ui/button";
import { Gated } from "@/components/ui/gated";

const STATUS_STYLE: Record<string, string> = {
  Pending: "border-card-edge bg-bg text-text-faint",
  Reviewing: "border-warn/30 bg-warn/10 text-warn",
  Rejected: "border-down/30 bg-down/10 text-down",
  Applied: "border-up/30 bg-up/10 text-up",
};

function SuggestionRow({
  suggestion,
  versions,
}: {
  suggestion: StrategySuggestion;
  versions: StrategyVersionSummary[];
}) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const jobQuery = useSuggestionReviewJob(jobId);
  const jobRunning = jobQuery.data?.status === "Running";
  const notifiedJobIdRef = useRef<string | null>(null);

  const trigger = useMutation({
    mutationFn: () => api.reviewSuggestion(suggestion.strategy_id, suggestion.id),
    onSuccess: (res) => setJobId(res.job_id),
  });

  useEffect(() => {
    if (jobId && jobQuery.data?.status === "Completed" && notifiedJobIdRef.current !== jobId) {
      notifiedJobIdRef.current = jobId;
      queryClient.invalidateQueries({ queryKey: ["suggestions", suggestion.strategy_id] });
      queryClient.invalidateQueries({ queryKey: ["strategy", suggestion.strategy_id] });
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobQuery.data?.status]);

  const resultingVersion = suggestion.resulting_version_id
    ? versions.find((v) => v.id === suggestion.resulting_version_id)
    : null;

  return (
    <div className="rounded-xl border border-card-edge bg-bg p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs leading-relaxed text-text">{suggestion.suggestion_text}</p>
        <span
          className={cn(
            "flex-shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium",
            STATUS_STYLE[suggestion.status] ?? "border-card-edge bg-bg text-text-faint",
          )}
        >
          {jobRunning ? "Reviewing…" : suggestion.status}
        </span>
      </div>

      {suggestion.ai_reasoning && (
        <p className="mt-2 text-[11px] leading-relaxed text-text-faint">
          <span className="font-medium text-text-dim">
            {suggestion.ai_verdict ? `${suggestion.ai_verdict} — ` : ""}
          </span>
          {suggestion.ai_reasoning}
        </p>
      )}

      {resultingVersion && (
        <p className="mt-1.5 text-[10px] text-up">
          → Applied as Version {resultingVersion.version_no}
        </p>
      )}

      {suggestion.status === "Pending" && (
        <Gated permission="reviewStrategySuggestion">
          <Button
            onClick={() => trigger.mutate()}
            disabled={trigger.isPending || jobRunning}
            className="mt-2.5 px-2.5 py-1 text-[11px]"
          >
            <Sparkles className="h-3 w-3" />
            {jobRunning ? "Reviewing…" : "Ask AI to Review"}
          </Button>
        </Gated>
      )}
    </div>
  );
}

/** REL-048/049: submit a free-text suggestion against this strategy; an AI agent reviews it
 * against the strategy's own current logic + latest backtest verdict and, if judged sound,
 * re-enters the real agent pipeline to produce a genuine new version + backtest for review --
 * never a silent field edit. Submitting is open to any authenticated user (server-enforced);
 * triggering the AI review is role-gated the same as triggering a backtest. */
export function SuggestionPanel({
  strategyId,
  versions,
}: {
  strategyId: string;
  versions: StrategyVersionSummary[];
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");

  const suggestionsQuery = useQuery({
    queryKey: ["suggestions", strategyId],
    queryFn: () => api.listSuggestions(strategyId),
  });

  const submit = useMutation({
    mutationFn: () => api.submitSuggestion(strategyId, text),
    onSuccess: () => {
      setText("");
      queryClient.invalidateQueries({ queryKey: ["suggestions", strategyId] });
    },
  });

  const suggestions = suggestionsQuery.data ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            "Suggest a change to this strategy's logic, e.g. tighten the stop-loss to reduce max drawdown…"
          }
          rows={2}
          className="w-full resize-none rounded-lg border border-card-edge bg-bg px-3 py-2 text-xs text-text placeholder:text-text-faint focus:outline-none focus:ring-1 focus:ring-brand-via/40"
        />
        <div className="flex items-center justify-between">
          <p className="text-[10px] text-text-faint">
            {submit.isError ? "Couldn't submit — try again." : "Any team member can suggest a change."}
          </p>
          <Button
            onClick={() => submit.mutate()}
            disabled={!text.trim() || submit.isPending}
            className="px-2.5 py-1 text-[11px]"
          >
            Submit Suggestion
          </Button>
        </div>
      </div>

      {suggestions.length > 0 && (
        <div className="flex flex-col gap-2">
          {suggestions.map((s) => (
            <SuggestionRow key={s.id} suggestion={s} versions={versions} />
          ))}
        </div>
      )}
    </div>
  );
}
