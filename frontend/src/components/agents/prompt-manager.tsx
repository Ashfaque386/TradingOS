"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { diffLines } from "diff";
import { Check, ChevronDown, GitCompare } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import type { PromptSummary } from "@/lib/api";

const TEMPLATE_VAR = /\{\{.*?\}\}|\{[a-zA-Z_][\w.]*\}/g;

/** Splits a prompt template on its own `{var}`/`{{ var }}` placeholder syntax and wraps each
 * match for a distinct color -- the "syntax-aware" upgrade the plain `<pre>` dump never had.
 * Not a general-purpose language highlighter (a prompt template isn't source code), just the one
 * real structural feature these templates actually have. */
function renderHighlighted(content: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  TEMPLATE_VAR.lastIndex = 0;
  let key = 0;
  while ((match = TEMPLATE_VAR.exec(content)) !== null) {
    if (match.index > lastIndex) parts.push(content.slice(lastIndex, match.index));
    parts.push(
      <span key={key++} className="text-brand-via">
        {match[0]}
      </span>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < content.length) parts.push(content.slice(lastIndex));
  return parts;
}

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
  const [diffAgainst, setDiffAgainst] = useState<number | null>(null);

  const contentQuery = useQuery({
    queryKey: ["prompt-content", prompt.agent_slug, previewVersion],
    queryFn: () => api.promptVersion(prompt.agent_slug, previewVersion),
    enabled: expanded,
  });

  const diffContentQuery = useQuery({
    queryKey: ["prompt-content", prompt.agent_slug, diffAgainst],
    queryFn: () => api.promptVersion(prompt.agent_slug, diffAgainst!),
    enabled: expanded && diffAgainst !== null,
  });

  const setActive = useMutation({
    mutationFn: (version: number) => api.setActivePromptVersion(prompt.agent_slug, version),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const diffing = diffAgainst !== null && diffAgainst !== previewVersion;

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
                  className="px-2.5 py-1 text-[10px]"
                >
                  <Check className="h-3 w-3" />
                  {setActive.isPending ? "Swapping…" : `Make v${previewVersion} active`}
                </Button>
              </Gated>
            )}
            {prompt.available_versions.length > 1 && (
              <div className="ml-auto flex items-center gap-1.5">
                <GitCompare className="h-3 w-3 text-text-faint" />
                <select
                  value={diffAgainst ?? ""}
                  onChange={(e) => setDiffAgainst(e.target.value === "" ? null : Number(e.target.value))}
                  className="rounded-md border border-card-edge bg-panel px-1.5 py-1 text-[10px] text-text-faint"
                >
                  <option value="">Diff against…</option>
                  {prompt.available_versions
                    .filter((v) => v !== previewVersion)
                    .map((v) => (
                      <option key={v} value={v}>
                        v{v}
                      </option>
                    ))}
                </select>
              </div>
            )}
          </div>

          {diffing ? (
            <PromptDiff
              oldLabel={`v${diffAgainst}`}
              newLabel={`v${previewVersion}`}
              oldContent={diffContentQuery.data?.content}
              newContent={contentQuery.data?.content}
            />
          ) : (
            <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-panel p-3 font-mono text-[10.5px] leading-relaxed text-text-dim">
              {contentQuery.data ? renderHighlighted(contentQuery.data.content) : "Loading…"}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function PromptDiff({
  oldLabel,
  newLabel,
  oldContent,
  newContent,
}: {
  oldLabel: string;
  newLabel: string;
  oldContent: string | undefined;
  newContent: string | undefined;
}) {
  if (oldContent === undefined || newContent === undefined) {
    return (
      <div className="rounded-lg bg-panel p-3 font-mono text-[10.5px] text-text-faint">
        Loading {oldLabel} → {newLabel}…
      </div>
    );
  }

  const parts = diffLines(oldContent, newContent);

  return (
    <div className="max-h-56 overflow-y-auto rounded-lg bg-panel font-mono text-[10.5px] leading-relaxed">
      <div className="sticky top-0 flex items-center gap-3 border-b border-card-edge bg-panel px-3 py-1.5 text-[9px] uppercase tracking-wider text-text-faint">
        <span className="text-down">− {oldLabel}</span>
        <span className="text-up">+ {newLabel}</span>
      </div>
      <div className="px-3 py-2">
        {parts.map((part, partIndex) => {
          const lines = part.value.split("\n").filter((line, idx, arr) => !(idx === arr.length - 1 && line === ""));
          return lines.map((line, lineIndex) => (
            <div
              key={`${partIndex}-${lineIndex}`}
              className={cn(
                "whitespace-pre-wrap px-1.5",
                part.added && "bg-up/10 text-up",
                part.removed && "bg-down/10 text-down",
                !part.added && !part.removed && "text-text-dim",
              )}
            >
              <span className="mr-1.5 select-none opacity-60">
                {part.added ? "+" : part.removed ? "−" : " "}
              </span>
              {line || " "}
            </div>
          ));
        })}
      </div>
    </div>
  );
}
