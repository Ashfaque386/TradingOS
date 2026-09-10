"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type AgentConfigTestResult } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Gated } from "@/components/ui/gated";

/** FR-108: run the selected prompt + (provider, model) against the real router once, without
 * activating anything. Reports provider/model/latency/structured-output-valid/errors. */
export function TestPanel({ slug, isLlmBacked }: { slug: string; isLlmBacked: boolean }) {
  const { data: providers } = useQuery({ queryKey: ["llm-providers"], queryFn: api.llmProviders });
  const [kind, setKind] = useState("system");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [result, setResult] = useState<AgentConfigTestResult | null>(null);

  const run = useMutation({
    mutationFn: () =>
      api.testAgentConfig(slug, {
        kind,
        ...(provider && model ? { provider, model } : {}),
      }),
    onSuccess: (r) => setResult(r),
  });

  const models = providers?.find((p) => p.provider === provider)?.models ?? [];

  if (!isLlmBacked) return null;

  return (
    <Gated permission="manageAgentConfig">
      <Card eyebrow="Test" title="Test panel" density="dense">
        <div className="flex flex-wrap gap-2">
          <select
            className="rounded-md border border-card-edge bg-bg px-1.5 py-1 text-xs"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            {["system", "task", "chat"].map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <select
            className="rounded-md border border-card-edge bg-bg px-1.5 py-1 text-xs"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setModel("");
            }}
          >
            <option value="">use configured / AUTO</option>
            {(providers ?? []).map((p) => (
              <option key={p.provider} value={p.provider}>
                {p.provider}
              </option>
            ))}
          </select>
          <select
            className="rounded-md border border-card-edge bg-bg px-1.5 py-1 text-xs"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={!provider}
          >
            <option value="">model…</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button
            className="rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground disabled:opacity-50"
            disabled={run.isPending}
            onClick={() => run.mutate()}
          >
            {run.isPending ? "Running…" : "Run test"}
          </button>
        </div>
        {result && (
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt className="text-text-muted">provider / model</dt>
            <dd className="text-right font-medium">
              {result.provider ?? "—"} / {result.model ?? "—"}
            </dd>
            <dt className="text-text-muted">latency</dt>
            <dd className="text-right">{result.latency_ms} ms</dd>
            <dt className="text-text-muted">structured output</dt>
            <dd className="text-right">
              <Badge variant={result.structured_output_valid ? "secondary" : "destructive"}>
                {result.structured_output_valid ? "valid" : "invalid"}
              </Badge>
            </dd>
            <dt className="text-text-muted">tool compatible</dt>
            <dd className="text-right">{result.tool_compatible ? "yes" : "no"}</dd>
            {result.errors.length > 0 && (
              <>
                <dt className="text-text-muted">errors</dt>
                <dd className="text-right text-destructive">{result.errors.join("; ")}</dd>
              </>
            )}
          </dl>
        )}
      </Card>
    </Gated>
  );
}
