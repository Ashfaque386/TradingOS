"use client";

import { use } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AgentDetail } from "@/components/console";
import { usePageStatus } from "@/hooks/usePageStatus";

export default function ConsoleAgentDetail({
  params,
}: {
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = use(params);
  const router = useRouter();
  const searchParams = useSearchParams();
  const runId = searchParams.get("runId") ?? undefined;
  const taskId = searchParams.get("taskId") ?? undefined;
  usePageStatus("Agent detail", true);
  return (
    <main className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <div className="flex items-center gap-3">
        <Link href="/console" className="text-[11px] text-text-faint hover:underline">
          ← Command Center
        </Link>
        {runId && (
          <Link
            href={`/console/runs/${runId}`}
            className="text-[11px] text-text-faint hover:underline"
          >
            ← Back to run
          </Link>
        )}
      </div>
      <AgentDetail
        agentId={decodeURIComponent(agentId)}
        runId={runId}
        taskId={taskId}
        onSwitchAgent={(nextAgentId) => {
          // Preserve the active run context (per spec 002 US4 AC6), but not the previous
          // agent's specific taskId -- the newly-selected agent has its own current task, not
          // this one. AgentDetail falls back to generic recent-activity when taskId is absent.
          const suffix = runId ? `?runId=${runId}` : "";
          router.push(`/console/agents/${nextAgentId}${suffix}`);
        }}
      />
    </main>
  );
}
