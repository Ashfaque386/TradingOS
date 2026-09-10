"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Gated } from "@/components/ui/gated";

/** FR-103: create a new prompt version. It is created **inactive** -- a separate Activate step
 * (audited) makes it live. SA only. */
export function PromptEditor({ slug }: { slug: string }) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState("system");
  const [content, setContent] = useState("");
  const [summary, setSummary] = useState("");
  const [ok, setOk] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.createAgentPrompt(slug, kind, content, summary),
    onSuccess: (v) => {
      setOk(`Created v${v.version} (inactive)`);
      setError(null);
      setContent("");
      setSummary("");
      queryClient.invalidateQueries({ queryKey: ["agent-prompt-versions", slug] });
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : "create failed");
      setOk(null);
    },
  });

  return (
    <Gated permission="manageAgentConfig">
      <Card eyebrow="Prompts" title="New version" density="dense">
        <div className="flex flex-col gap-2">
          <select
            className="w-32 rounded-md border border-card-edge bg-bg px-1.5 py-1 text-xs"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            {["system", "task", "chat"].map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <textarea
            className="min-h-[160px] w-full rounded-md border border-card-edge bg-bg p-2 font-mono text-[11px]"
            placeholder="Prompt content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
          <input
            className="w-full rounded-md border border-card-edge bg-bg p-1.5 text-xs"
            placeholder="Change summary (required)"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
          />
          <button
            className="w-fit rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground disabled:opacity-50"
            disabled={!content.trim() || !summary.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            Create inactive version
          </button>
          {ok && <p className="text-[11px] text-emerald-400">{ok}</p>}
          {error && <p className="text-[11px] text-destructive">{error}</p>}
        </div>
      </Card>
    </Gated>
  );
}
