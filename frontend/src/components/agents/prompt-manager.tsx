"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import type { PromptSummary } from "@/lib/api";

export function PromptManager() {
  const { data: prompts } = useQuery({ queryKey: ["prompts"], queryFn: api.prompts });
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!prompts || prompts.length === 0) {
    return <p className="text-xs text-text-faint">No agents registered in the prompt registry.</p>;
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
    <div className="rounded-xl border border-card-edge bg-bg">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left"
      >
        <div className="flex items-center gap-2.5">
          <ChevronDown
            className={cn("h-3.5 w-3.5 text-text-faint transition-transform", expanded && "rotate-180")}
          />
          <span className="text-xs font-medium text-text">{prompt.agent_slug}</span>
          <span className="rounded-full bg-panel px-1.5 py-0.5 text-[9px] text-text-faint">
            {prompt.prompt_id}
          </span>
        </div>
        <span className="text-[10px] text-up/80">v{prompt.active_version} active</span>
      </button>

      {expanded && (
        <div className="border-t border-card-edge px-3.5 py-3">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            {prompt.available_versions.map((v) => (
              <button
                key={v}
                onClick={() => setPreviewVersion(v)}
                className={cn(
                  "rounded-md px-2 py-1 text-[10px] font-medium transition-colors",
                  v === previewVersion
                    ? "bg-brand-via/15 text-brand-via"
                    : "bg-panel text-text-faint hover:text-text-dim",
                )}
              >
                v{v}
              </button>
            ))}
            {previewVersion !== prompt.active_version && (
              <Gated permission="swapActivePrompt">
                <Button
                  onClick={() => setActive.mutate(previewVersion)}
                  disabled={setActive.isPending}
                  className="ml-auto px-2.5 py-1 text-[10px]"
                >
                  <Check className="h-3 w-3" />
                  {setActive.isPending ? "Swapping…" : `Make v${previewVersion} active`}
                </Button>
              </Gated>
            )}
          </div>
          <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-panel p-3 font-mono text-[10.5px] leading-relaxed text-text-dim">
            {contentQuery.data?.content ?? "Loading…"}
          </pre>
        </div>
      )}
    </div>
  );
}
