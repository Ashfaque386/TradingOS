"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { usePageStatus } from "@/hooks/usePageStatus";
import {
  PromptEditor,
  PromptVersionHistory,
  ProviderHealth,
  ProviderModelPanel,
  SkillGrantPanel,
  TestPanel,
} from "@/components/agent-settings";

/** FR-100: per-agent Settings, distinct from global /settings. `agentId` is the prompt-registry
 * slug (e.g. `market_analyst_agent`). */
export default function AgentSettingsPage({
  params,
}: {
  params: Promise<{ agentId: string }>;
}) {
  const { agentId } = use(params);
  const slug = decodeURIComponent(agentId);
  usePageStatus("Agent Settings", true);

  const { data: config, isLoading } = useQuery({
    queryKey: ["agent-config", slug],
    queryFn: () => api.agentConfig(slug),
  });
  // spec 002 US8: AgentSkillMap keys by the real KNOWN_AGENTS name (e.g. "market_analyst"),
  // which isn't always identical to this page's own prompt-registry slug (e.g.
  // "market_analyst_agent") -- resolve it once against the real Agent Registry rather than
  // guessing a suffix rule, honestly falling back to the slug itself if no match is found.
  const { data: registry } = useQuery({ queryKey: ["agent-registry"], queryFn: api.agentRegistry });
  const resolvedAgentName =
    registry?.find((a) => a.agent_name === slug || a.agent_name === slug.replace(/_agent$/, ""))
      ?.agent_name ?? slug;

  return (
    <main className="mx-auto flex w-full max-w-[1100px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <Link href="/settings" className="text-[11px] text-text-faint hover:underline">
        ← Settings
      </Link>
      <div>
        <h1 className="text-lg font-semibold">{slug}</h1>
        <p className="text-[11px] text-text-faint">
          Per-agent prompt versions and model routing. Changes are SystemAdministrator-only and
          audited; AUTO keeps today&rsquo;s routing unchanged.
        </p>
      </div>

      {isLoading || !config ? (
        <div className="h-24 animate-pulse rounded-card bg-bg" />
      ) : (
        <>
          <Card eyebrow="Config" title="Effective configuration" density="dense">
            <div className="flex flex-wrap gap-1.5 text-xs">
              <Badge variant={config.is_llm_backed ? "secondary" : "outline"}>
                {config.is_llm_backed ? "LLM-backed" : "deterministic"}
              </Badge>
              <Badge variant="outline">model: {config.provider_model}</Badge>
              <Badge variant="outline">{config.precedence}</Badge>
              {Object.entries(config.active_prompts).map(([k, v]) => (
                <Badge key={k} variant="outline">
                  {k} prompt: v{v ?? "—"}
                </Badge>
              ))}
            </div>
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <ProviderModelPanel config={config} />
            <ProviderHealth />
          </div>

          <PromptVersionHistory slug={slug} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <PromptEditor slug={slug} />
            <TestPanel slug={slug} isLlmBacked={config.is_llm_backed} />
          </div>
          <SkillGrantPanel agentName={resolvedAgentName} />
        </>
      )}
    </main>
  );
}
