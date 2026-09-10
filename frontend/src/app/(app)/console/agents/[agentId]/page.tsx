"use client";

import { use } from "react";
import Link from "next/link";
import { AgentDetail } from "@/components/console";
import { usePageStatus } from "@/hooks/usePageStatus";

export default function ConsoleAgentDetail({
  params,
}: {
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = use(params);
  usePageStatus("Agent detail", true);
  return (
    <main className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <Link href="/console" className="text-[11px] text-text-faint hover:underline">
        ← Command Center
      </Link>
      <AgentDetail agentId={decodeURIComponent(agentId)} />
    </main>
  );
}
