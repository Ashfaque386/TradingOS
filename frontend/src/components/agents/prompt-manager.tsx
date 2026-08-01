"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import type { PromptSummary } from "@/lib/api";

export function PromptManager() {
  const { data: prompts } = useQuery({ queryKey: ["prompts"], queryFn: api.prompts });
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!prompts || prompts.length === 0) {
    return <p className="text-xs text-zinc-500">No agents registered in the prompt registry.</p>;
  }

  return (
    <div className="space-y-1.5">
      {prompts.map((p) => (
        <PromptRow
          key={p.agent_slug}
          prompt={p}
          expanded={expanded === p.agent_slug}
          onToggle={() => setExpanded(expanded === p.agent_slug ? null : p.agent_slug)}
        />
      ))}
    </div>
  );
}

function PromptRow({
  prompt,
  expanded,
  onToggle,
}: {
  prompt: PromptSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const queryClient = useQueryClient();
  const [previewVersion, setPreviewVersion] = useState(prompt.active_version);

  const contentQuery = useQuery({
    queryKey: ["prompt-content", prompt.agent_slug, previewVersion],
    queryFn: () => api.promptVersion(prompt.agent_slug, previewVersion),
    enabled: expanded,
  });

  const setActive = useMutation({
    mutationFn: (version: number) => api.setActivePromptVersion(prompt.agent_slug, version),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  return (
    <div className="rounded-xl border border-white/5 bg-black/20">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left"
      >
        <div className="flex items-center gap-2.5">
          <ChevronDown
            className={cn("h-3.5 w-3.5 text-zinc-500 transition-transform", expanded && "rotate-180")}
          />
          <span className="text-xs font-medium text-zinc-200">{prompt.agent_slug}</span>
          <span className="rounded-full bg-white/5 px-1.5 py-0.5 text-[9px] text-zinc-500">
            {prompt.prompt_id}
          </span>
        </div>
        <span className="text-[10px] text-emerald-300/80">v{prompt.active_version} active</span>
      </button>

      {expanded && (
        <div className="border-t border-white/5 px-3.5 py-3">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            {prompt.available_versions.map((v) => (
              <button
                key={v}
                onClick={() => setPreviewVersion(v)}
                className={cn(
                  "rounded-md px-2 py-1 text-[10px] font-medium transition-colors",
                  v === previewVersion
                    ? "bg-cyan-400/15 text-cyan-200"
                    : "bg-white/5 text-zinc-500 hover:text-zinc-300",
                )}
              >
                v{v}
              </button>
            ))}
            {previewVersion !== prompt.active_version && (
              <Gated permission="swapActivePrompt">
                <button
                  onClick={() => setActive.mutate(previewVersion)}
                  disabled={setActive.isPending}
                  className="ml-auto flex items-center gap-1 rounded-md bg-emerald-500/90 px-2.5 py-1 text-[10px] font-semibold text-black transition hover:bg-emerald-400 disabled:opacity-50"
                >
                  <Check className="h-3 w-3" />
                  {setActive.isPending ? "Swapping…" : `Make v${previewVersion} active`}
                </button>
              </Gated>
            )}
          </div>
          <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-black/40 p-3 font-mono text-[10.5px] leading-relaxed text-zinc-400">
            {contentQuery.data?.content ?? "Loading…"}
          </pre>
        </div>
      )}
    </div>
  );
}
