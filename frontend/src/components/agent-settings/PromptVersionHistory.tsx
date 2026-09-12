"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Gated } from "@/components/ui/gated";
import { PromptDiff } from "./PromptDiff";

/** FR-101/102/103: prompt version history per kind, with a two-version diff and (SA-only)
 * activate / rollback. Activation is audited server-side and takes effect on the next run. */
export function PromptVersionHistory({ slug }: { slug: string }) {
  const queryClient = useQueryClient();
  const { data: versions, isLoading } = useQuery({
    queryKey: ["agent-prompt-versions", slug],
    queryFn: () => api.agentPromptVersions(slug),
  });

  const [kind, setKind] = useState<string>("system");
  const kinds = useMemo(
    () => [...new Set((versions ?? []).map((v) => v.kind))].sort(),
    [versions],
  );
  const forKind = (versions ?? []).filter((v) => v.kind === (kinds.includes(kind) ? kind : kinds[0]));

  const [left, setLeft] = useState<number | null>(null);
  const [right, setRight] = useState<number | null>(null);
  const leftQ = useQuery({
    queryKey: ["agent-prompt", slug, kind, left],
    queryFn: () => api.agentPromptVersion(slug, kind, left!),
    enabled: left != null,
  });
  const rightQ = useQuery({
    queryKey: ["agent-prompt", slug, kind, right],
    queryFn: () => api.agentPromptVersion(slug, kind, right!),
    enabled: right != null,
  });

  // spec 002 US9: activation/rollback must be preceded by actually opening that version's diff
  // (C-4) -- recorded directly in the diff L/R click handlers below (a normal event-driven
  // state update, not derived from an effect), and requires a second explicit confirm click
  // after that, so a SA can't blind-activate/-rollback a version they never looked at.
  const [diffedVersions, setDiffedVersions] = useState<Set<number>>(new Set());
  const markDiffed = (version: number) =>
    setDiffedVersions((prev) => (prev.has(version) ? prev : new Set(prev).add(version)));
  const [confirmingActivate, setConfirmingActivate] = useState<number | null>(null);
  const [confirmingRollback, setConfirmingRollback] = useState<number | null>(null);

  const [error, setError] = useState<string | null>(null);
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["agent-prompt-versions", slug] });
    queryClient.invalidateQueries({ queryKey: ["agent-config", slug] });
  };
  const activate = useMutation({
    mutationFn: (v: number) => api.activateAgentPrompt(slug, kind, v),
    onSuccess: () => {
      setError(null);
      setConfirmingActivate(null);
      invalidate();
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "activate failed"),
  });
  const rollback = useMutation({
    mutationFn: (v: number) => api.rollbackAgentPrompt(slug, kind, v),
    onSuccess: () => {
      setError(null);
      setConfirmingRollback(null);
      invalidate();
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "rollback failed"),
  });

  return (
    <Card
      eyebrow="Prompts"
      title="Version history"
      density="dense"
      action={
        <select
          className="rounded-md border border-card-edge bg-bg px-1.5 py-0.5 text-[11px]"
          value={kinds.includes(kind) ? kind : kinds[0]}
          onChange={(e) => setKind(e.target.value)}
        >
          {(kinds.length ? kinds : ["system"]).map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      }
    >
      {isLoading ? (
        <div className="h-10 animate-pulse rounded bg-bg" />
      ) : forKind.length === 0 ? (
        <p className="text-[11px] italic text-text-faint">No versions yet for this kind.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {forKind
            .slice()
            .sort((a, b) => b.version - a.version)
            .map((v) => (
              <li
                key={v.version}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-card-edge p-2 text-xs"
              >
                <span className="font-semibold">v{v.version}</span>
                {v.is_active && <Badge variant="secondary">active</Badge>}
                <span className="text-text-muted">{v.change_summary}</span>
                <span className="text-text-faint">· {v.author}</span>
                <div className="ml-auto flex gap-1.5">
                  <button
                    className="rounded-md border border-card-edge px-1.5 py-0.5 text-[11px]"
                    onClick={() => {
                      setLeft(v.version);
                      markDiffed(v.version);
                    }}
                  >
                    diff L
                  </button>
                  <button
                    className="rounded-md border border-card-edge px-1.5 py-0.5 text-[11px]"
                    onClick={() => {
                      setRight(v.version);
                      markDiffed(v.version);
                    }}
                  >
                    diff R
                  </button>
                  <Gated permission="manageAgentConfig">
                    {(() => {
                      const diffed = diffedVersions.has(v.version);
                      if (confirmingActivate === v.version) {
                        return (
                          <>
                            <span className="text-[11px] text-text-faint">Activate v{v.version}?</span>
                            <button
                              className="rounded-md bg-primary px-1.5 py-0.5 text-[11px] text-primary-foreground disabled:opacity-50"
                              disabled={activate.isPending}
                              onClick={() => activate.mutate(v.version)}
                            >
                              Confirm
                            </button>
                            <button
                              className="rounded-md border border-card-edge px-1.5 py-0.5 text-[11px]"
                              onClick={() => setConfirmingActivate(null)}
                            >
                              Cancel
                            </button>
                          </>
                        );
                      }
                      return (
                        <button
                          className="rounded-md bg-primary px-1.5 py-0.5 text-[11px] text-primary-foreground disabled:opacity-50"
                          disabled={v.is_active || activate.isPending || !diffed}
                          title={diffed ? undefined : "View this version's diff first"}
                          onClick={() => setConfirmingActivate(v.version)}
                        >
                          Activate
                        </button>
                      );
                    })()}
                    {(() => {
                      const diffed = diffedVersions.has(v.version);
                      if (confirmingRollback === v.version) {
                        return (
                          <>
                            <span className="text-[11px] text-text-faint">Roll back to v{v.version}?</span>
                            <button
                              className="rounded-md border border-card-edge px-1.5 py-0.5 text-[11px] disabled:opacity-50"
                              disabled={rollback.isPending}
                              onClick={() => rollback.mutate(v.version)}
                            >
                              Confirm
                            </button>
                            <button
                              className="rounded-md border border-card-edge px-1.5 py-0.5 text-[11px]"
                              onClick={() => setConfirmingRollback(null)}
                            >
                              Cancel
                            </button>
                          </>
                        );
                      }
                      return (
                        <button
                          className="rounded-md border border-card-edge px-1.5 py-0.5 text-[11px] disabled:opacity-50"
                          disabled={rollback.isPending || !diffed}
                          title={diffed ? undefined : "View this version's diff first"}
                          onClick={() => setConfirmingRollback(v.version)}
                        >
                          Roll back
                        </button>
                      );
                    })()}
                  </Gated>
                </div>
              </li>
            ))}
        </ul>
      )}

      {error && <p className="mt-2 text-[11px] text-destructive">{error}</p>}

      {left != null && right != null && leftQ.data && rightQ.data && (
        <div className="mt-3">
          <div className="mb-1 text-[11px] text-text-faint">
            v{left} → v{right}
          </div>
          <PromptDiff before={leftQ.data.content} after={rightQ.data.content} />
        </div>
      )}
    </Card>
  );
}
