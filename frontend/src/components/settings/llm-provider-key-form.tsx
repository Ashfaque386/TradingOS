"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import type { LlmProviderId } from "@/lib/api";

const PROVIDERS: { id: LlmProviderId; label: string }[] = [
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic (Claude)" },
  { id: "deepseek", label: "DeepSeek" },
  { id: "gemini", label: "Gemini" },
  { id: "huggingface", label: "HuggingFace" },
  { id: "opencode", label: "OpenCode Zen" },
];

/** REL-021 E21.2: write-only credential management against src/api/routers/settings.py's new
 * llm-provider-keys endpoints -- same shape as BrokerCredentialsForm (REL-017 E17.2), never
 * round-trips a stored secret. Ollama is deliberately absent from the picker: it needs no API
 * key (src/agents/llm_router.py::resolve_api_key returns None for it unconditionally). */
export function LlmProviderKeyForm() {
  const [provider, setProvider] = useState<LlmProviderId>("openai");
  const [apiKey, setApiKey] = useState("");
  const queryClient = useQueryClient();

  const write = useMutation({
    mutationFn: () => api.writeLlmProviderKey(provider, apiKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations-status"] });
      setApiKey("");
    },
  });

  const remove = useMutation({
    mutationFn: () => api.deleteLlmProviderKey(provider),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations-status"] }),
  });

  return (
    <Gated
      permission="manageLlmProviderKeys"
      fallback={
        <p className="mt-3 text-[11px] text-text-faint">
          Only a SystemAdministrator can write or remove LLM provider keys.
        </p>
      }
    >
      <div className="mt-3 rounded-xl border border-card-edge bg-bg p-3.5">
        <div className="flex items-center gap-2">
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as LlmProviderId)}
            className="rounded-md border border-card-edge bg-panel px-2 py-1.5 text-xs text-text"
          >
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
          <button
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            title={`Remove the stored ${provider} key from Vault`}
            className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-text-faint transition hover:bg-down/10 hover:text-down"
          >
            <Trash2 className="h-3 w-3" /> Remove
          </button>
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="API key"
            autoComplete="off"
            className="min-w-[160px] flex-1 rounded-md border border-card-edge bg-panel px-2 py-1.5 text-xs text-text placeholder:text-text-faint"
          />
          <Button
            onClick={() => write.mutate()}
            disabled={apiKey.trim() === "" || write.isPending}
            className="px-3 py-1.5 text-[11px]"
          >
            {write.isPending ? "Saving…" : "Save to Vault"}
          </Button>
          {write.isError && (
            <p className="w-full text-[10px] text-down">Failed to write key.</p>
          )}
        </div>
      </div>
    </Gated>
  );
}
