"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AgentConfigView } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Gated } from "@/components/ui/gated";

/** FR-104/105 (clarify Q5): AUTO (today's routing, unchanged) vs a CUSTOM (provider, model)
 * pair chosen only from configured+valid options. A deterministic agent shows no picker. */
export function ProviderModelPanel({ config }: { config: AgentConfigView }) {
  const queryClient = useQueryClient();
  const { data: providers } = useQuery({
    queryKey: ["llm-providers"],
    queryFn: api.llmProviders,
  });

  const [initialProvider, initialModel] = config.provider_model.includes("/")
    ? config.provider_model.split("/")
    : ["", ""];
  const [mode, setMode] = useState<"AUTO" | "CUSTOM">(
    config.provider_model_mode === "CUSTOM" ? "CUSTOM" : "AUTO",
  );
  const [provider, setProvider] = useState<string>(initialProvider);
  const [model, setModel] = useState<string>(initialModel);
  const [error, setError] = useState<string | null>(null);

  const models = providers?.find((p) => p.provider === provider)?.models ?? [];

  const save = useMutation({
    mutationFn: () =>
      api.setAgentProviderModel(
        config.agent_slug,
        mode === "AUTO" ? { mode } : { mode, provider, model },
      ),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["agent-config", config.agent_slug] });
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "save failed"),
  });

  if (!config.is_llm_backed) {
    return (
      <Card eyebrow="Model" title="Provider / model" density="dense">
        <p className="text-xs text-text-muted">
          <Badge variant="outline">deterministic</Badge> This agent runs deterministic logic —
          there is no model to configure.
        </p>
      </Card>
    );
  }

  return (
    <Card eyebrow="Model" title="Provider / model" density="dense">
      <div className="text-xs text-text-muted">
        Effective: <span className="font-medium text-text">{config.provider_model}</span> ·{" "}
        {config.precedence}
      </div>
      <Gated permission="manageAgentConfig">
        <div className="mt-2 flex flex-col gap-2">
          <div className="flex gap-3 text-xs">
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={mode === "AUTO"}
                onChange={() => setMode("AUTO")}
              />
              AUTO (routing.yaml — unchanged)
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={mode === "CUSTOM"}
                onChange={() => setMode("CUSTOM")}
              />
              CUSTOM
            </label>
          </div>
          {mode === "CUSTOM" && (
            <div className="flex gap-2">
              <select
                className="rounded-md border border-card-edge bg-bg px-1.5 py-1 text-xs"
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value);
                  setModel("");
                }}
              >
                <option value="">provider…</option>
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
            </div>
          )}
          <button
            className="w-fit rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground disabled:opacity-50"
            disabled={
              save.isPending || (mode === "CUSTOM" && (!provider || !model))
            }
            onClick={() => save.mutate()}
          >
            Save
          </button>
          {error && <p className="text-[11px] text-destructive">{error}</p>}
        </div>
      </Gated>
    </Card>
  );
}
