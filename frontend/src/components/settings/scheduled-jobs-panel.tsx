"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  Ban,
  CircleCheck,
  Clock,
  Info,
  Lock,
  Play,
  Sparkles,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import { usePermission } from "@/lib/usePermission";
import { ScheduleBuilder } from "@/components/settings/schedule-builder";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { ScheduledJobRunEntry, ScheduledJobSummary } from "@/lib/api";

const RUN_STATUS_DOT: Record<string, string> = {
  Running: "bg-brand-via",
  Completed: "bg-up",
  Failed: "bg-down",
  Skipped: "bg-warn",
};

const RUN_STATUS_TEXT: Record<string, string> = {
  Running: "text-brand-via",
  Completed: "text-up",
  Failed: "text-down",
  Skipped: "text-warn",
};

const HISTORY_PAGE_SIZE = 10;

/** Handles both a past `last_run.started_at` and a future `next_run_time` -- REL-081's history
 * and schedule fields share exactly the same "relative to now" display need, so one function
 * covers both directions rather than one past-only helper (run-controls.tsx's own `relativeTime`)
 * plus a second future-only one. */
function relativeToNow(iso: string): string {
  const deltaMs = new Date(iso).getTime() - Date.now();
  const future = deltaMs >= 0;
  const abs = Math.abs(deltaMs);
  const minutes = Math.round(abs / 60_000);
  let text: string;
  if (minutes < 1) text = "now";
  else if (minutes < 60) text = `${minutes}m`;
  else if (minutes < 60 * 24) text = `${Math.round(minutes / 60)}h`;
  else text = `${Math.round(minutes / (60 * 24))}d`;
  if (text === "now") return "now";
  return future ? `in ${text}` : `${text} ago`;
}

function duration(run: ScheduledJobRunEntry): string | null {
  if (!run.ended_at) return null;
  const ms = new Date(run.ended_at).getTime() - new Date(run.started_at).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

function RunStatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={cn("gap-1 border-transparent bg-panel", RUN_STATUS_TEXT[status])}>
      <span className={cn("h-1.5 w-1.5 rounded-full", RUN_STATUS_DOT[status] ?? "bg-text-faint")} />
      {status}
    </Badge>
  );
}

/** REL-081: full in-app control for the 11 real scheduled jobs (7 pre-existing + the 4 that used
 * to run as external Windows Scheduled Tasks) -- replaces the "State=Ready" illusion of the OS
 * task list with real schedule/history/status, editable without a container restart. Structurally
 * cloned from agent-registry.tsx's proven Table+Sheet shape. */
export function ScheduledJobsPanel() {
  const queryClient = useQueryClient();
  const [detailJobId, setDetailJobId] = useState<string | null>(null);

  const jobsQuery = useQuery({
    queryKey: ["scheduled-jobs"],
    queryFn: api.scheduledJobsList,
    refetchInterval: 15_000,
  });

  const runNow = useMutation({
    mutationFn: (jobId: string) => api.runScheduledJobNow(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["scheduled-job-history"] });
    },
  });

  const jobs = jobsQuery.data ?? [];
  const detailJob = jobs.find((j) => j.job_id === detailJobId) ?? null;

  if (jobsQuery.isLoading) {
    return <div className="h-40 animate-pulse rounded-xl bg-bg" />;
  }

  if (jobsQuery.isError) {
    return <p className="text-xs text-down">Failed to load scheduled jobs.</p>;
  }

  return (
    <>
      <div className="overflow-x-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="h-auto px-0 pb-2 text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Job
              </TableHead>
              <TableHead className="h-auto px-0 pb-2 text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Schedule
              </TableHead>
              <TableHead className="h-auto px-0 pb-2 text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Status
              </TableHead>
              <TableHead className="h-auto px-0 pb-2 text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Last Run
              </TableHead>
              <TableHead className="h-auto px-0 pb-2 text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Next Run
              </TableHead>
              <TableHead className="h-auto px-0 pb-2 text-right text-[10px] font-medium uppercase tracking-wider text-text-faint">
                Actions
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => {
              const isPendingThis = runNow.isPending && runNow.variables === job.job_id;
              return (
                <TableRow key={job.job_id} className="border-card-edge align-top">
                  <TableCell className="px-0 py-row-dense">
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[11px] font-medium text-text">{job.display_name}</span>
                        {job.is_new && (
                          <span title="Newly moved in-app from an external Windows Scheduled Task">
                            <Sparkles className="h-2.5 w-2.5 text-brand-via" />
                          </span>
                        )}
                      </div>
                      <span className="font-mono-tabular text-[9px] text-text-faint">{job.job_id}</span>
                    </div>
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-text-dim">{job.human_readable}</span>
                      <span className="font-mono-tabular text-[9px] text-text-faint">
                        {job.cron_expression}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    <Badge
                      variant="outline"
                      className={cn(
                        "w-fit border-transparent",
                        job.enabled ? "text-up" : "text-down",
                      )}
                    >
                      {job.enabled ? (
                        <CircleCheck className="h-2.5 w-2.5" />
                      ) : (
                        <Ban className="h-2.5 w-2.5" />
                      )}
                      {job.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    {job.last_run ? (
                      <div className="flex flex-col gap-1">
                        <RunStatusBadge status={job.last_run.status} />
                        <span className="text-[10px] text-text-faint">
                          {relativeToNow(job.last_run.started_at)}
                          {job.last_run.trigger_source === "manual" && " · manual"}
                        </span>
                      </div>
                    ) : (
                      <span className="text-[10px] text-text-faint">Never run</span>
                    )}
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    <span className="text-[10px] text-text-faint">
                      {job.next_run_time ? relativeToNow(job.next_run_time) : "Paused"}
                    </span>
                  </TableCell>
                  <TableCell className="px-0 py-row-dense">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => setDetailJobId(job.job_id)}
                        title="View details"
                        className="rounded-md p-1 text-text-faint transition hover:bg-bg hover:text-text-dim"
                      >
                        <Info className="h-3.5 w-3.5" />
                      </button>
                      <Gated permission="runScheduledJobNow" fallback={null}>
                        <Button
                          onClick={() => runNow.mutate(job.job_id)}
                          disabled={isPendingThis}
                          variant="secondary"
                          className="shrink-0 px-2 py-1 text-[10px]"
                        >
                          <Play className="h-3 w-3" /> {isPendingThis ? "Running…" : "Run now"}
                        </Button>
                      </Gated>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <Sheet open={detailJob !== null} onOpenChange={(open) => !open && setDetailJobId(null)}>
        <SheetContent className="sm:max-w-xl">
          {detailJob && <ScheduledJobDetailPanel job={detailJob} />}
        </SheetContent>
      </Sheet>
    </>
  );
}

function ScheduledJobDetailPanel({ job }: { job: ScheduledJobSummary }) {
  const queryClient = useQueryClient();
  const [cronDraft, setCronDraft] = useState(job.cron_expression);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [loadedHistory, setLoadedHistory] = useState<ScheduledJobRunEntry[]>([]);
  // Only ReadOnlyAuditor lands here now (view is broader than manage) -- shown as an honest
  // banner rather than the controls just silently not being there, which is what a viewer in
  // that role actually saw before this was added.
  const canManage = usePermission("manageScheduledJobs");

  const historyQuery = useQuery({
    queryKey: ["scheduled-job-history", job.job_id, historyOffset],
    queryFn: () => api.scheduledJobHistory(job.job_id, HISTORY_PAGE_SIZE, historyOffset),
  });

  const allHistory = historyOffset === 0 ? historyQuery.data ?? [] : [...loadedHistory, ...(historyQuery.data ?? [])];
  const canLoadMore = (historyQuery.data?.length ?? 0) === HISTORY_PAGE_SIZE;

  const update = useMutation({
    mutationFn: (body: { cron_expression?: string; enabled?: boolean }) =>
      api.updateScheduledJobConfig(job.job_id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-jobs"] });
    },
  });

  const runNow = useMutation({
    mutationFn: () => api.runScheduledJobNow(job.job_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["scheduled-job-history", job.job_id] });
    },
  });

  const cronDirty = cronDraft !== job.cron_expression;
  // Client-side sanity check only -- a genuinely valid-but-unusual expression still round-trips
  // through the server's own real CronTrigger.from_crontab validation on submit.
  const cronLooksValid = cronDraft.trim().split(/\s+/).length === 5;

  return (
    <>
      <SheetHeader>
        <SheetTitle>{job.display_name}</SheetTitle>
        <SheetDescription>{job.description}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-5 px-4 pb-6 text-xs">
        {!canManage && (
          <div className="flex items-start gap-2 rounded-xl border border-card-edge bg-bg p-3 text-[10px] text-text-faint">
            <Lock className="mt-0.5 h-3 w-3 shrink-0" />
            <span>
              Read-only for your role. Editing the schedule, enabling/disabling, and Run Now need
              System Administrator, Portfolio Manager, or Risk Manager.
            </span>
          </div>
        )}

        <DetailRow label="Job ID" value={job.job_id} mono />

        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] uppercase tracking-wider text-text-faint">Schedule</span>
          <ScheduleBuilder value={cronDraft} onChange={setCronDraft} disabled={!canManage} />
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] text-text-faint">
              {cronDirty && !cronLooksValid
                ? "A cron expression needs exactly 5 space-separated fields."
                : job.human_readable}
            </span>
            <Gated permission="manageScheduledJobs" fallback={null}>
              <Button
                onClick={() => update.mutate({ cron_expression: cronDraft })}
                disabled={!cronDirty || !cronLooksValid || update.isPending}
                className="shrink-0 px-2.5 py-1.5 text-[10px]"
              >
                {update.isPending ? "Saving…" : "Save"}
              </Button>
            </Gated>
          </div>
          {canManage && cronDraft !== job.default_cron_expression && (
            <button
              onClick={() => setCronDraft(job.default_cron_expression)}
              className="w-fit text-[10px] text-text-faint underline decoration-dotted hover:text-text-dim"
            >
              Reset to default ({job.default_cron_expression})
            </button>
          )}
          {update.isError && (
            <span className="text-[10px] text-down">
              {update.error instanceof Error ? update.error.message : "Failed to update schedule."}
            </span>
          )}
        </div>

        <div className="flex items-center justify-between rounded-xl border border-card-edge bg-bg p-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-[11px] font-medium text-text">
              {job.enabled ? "Enabled" : "Disabled"}
            </span>
            <span className="text-[10px] text-text-faint">
              {job.enabled ? "Fires on its own schedule." : "Never fires until re-enabled."}
            </span>
          </div>
          <Gated
            permission="manageScheduledJobs"
            fallback={
              <Badge variant="outline" className={job.enabled ? "text-up" : "text-down"}>
                {job.enabled ? "Enabled" : "Disabled"}
              </Badge>
            }
          >
            <Button
              onClick={() => update.mutate({ enabled: !job.enabled })}
              disabled={update.isPending}
              variant={job.enabled ? "destructive" : "primary"}
              className="px-2.5 py-1.5 text-[10px]"
            >
              {job.enabled ? (
                <>
                  <Ban className="h-3 w-3" /> Disable
                </>
              ) : (
                <>
                  <CircleCheck className="h-3 w-3" /> Enable
                </>
              )}
            </Button>
          </Gated>
        </div>

        <Gated permission="runScheduledJobNow" fallback={null}>
          <Button
            onClick={() => runNow.mutate()}
            disabled={runNow.isPending}
            variant="secondary"
            className="w-full py-2 text-[11px]"
          >
            <Play className="h-3.5 w-3.5" /> {runNow.isPending ? "Running…" : "Run now"}
          </Button>
          {runNow.isError && (
            <span className="-mt-3 text-[10px] text-down">
              {runNow.error instanceof Error ? runNow.error.message : "Failed to dispatch run."}
            </span>
          )}
        </Gated>

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-faint">
            <Clock className="h-3 w-3" /> Execution history
          </div>
          {historyQuery.isLoading && historyOffset === 0 ? (
            <div className="h-16 animate-pulse rounded-xl bg-bg" />
          ) : allHistory.length === 0 ? (
            <p className="text-[10px] text-text-faint">No runs recorded yet.</p>
          ) : (
            <div className="flex flex-col divide-y divide-card-edge overflow-hidden rounded-xl border border-card-edge">
              {allHistory.map((run) => (
                <div key={run.id} className="flex flex-col gap-1 bg-bg p-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <RunStatusBadge status={run.status} />
                    <span className="font-mono-tabular text-[9px] text-text-faint">
                      {new Date(run.started_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-text-faint">
                    <span>{run.trigger_source === "manual" ? "Manual" : "Cron"}</span>
                    {duration(run) && <span>· {duration(run)}</span>}
                    {run.triggered_by && <span>· by {run.triggered_by}</span>}
                  </div>
                  {run.result_summary && (
                    <p className="flex items-start gap-1 text-[10px] text-text-dim">
                      {run.status === "Failed" ? (
                        <XCircle className="mt-0.5 h-2.5 w-2.5 shrink-0 text-down" />
                      ) : null}
                      <span className="break-words">{run.result_summary}</span>
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
          {canLoadMore && (
            <button
              onClick={() => {
                setLoadedHistory(allHistory);
                setHistoryOffset((prev) => prev + HISTORY_PAGE_SIZE);
              }}
              disabled={historyQuery.isFetching}
              className="w-full rounded-lg border border-dashed border-card-edge py-1.5 text-[10px] text-text-faint transition hover:border-text-faint hover:text-text-dim"
            >
              {historyQuery.isFetching ? "Loading…" : "Load more"}
            </button>
          )}
        </div>
      </div>
    </>
  );
}

function DetailRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wider text-text-faint">{label}</span>
      <span className={cn("text-text", mono && "font-mono-tabular text-[11px]")}>{value}</span>
    </div>
  );
}
