"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Gated } from "@/components/ui/gated";
import { Button } from "@/components/ui/button";
import type { BrokerId } from "@/lib/api";

/** REL-017 E17.2: write-only credential management against src/api/routers/broker_config.py.
 * Never round-trips a stored secret -- there is no GET-credentials endpoint anywhere in this
 * codebase by design (src/core/vault.py has no method that returns a raw value to an API layer
 * caller); this form can only write a new value or delete the stored one, matching that. */
export function BrokerCredentialsForm() {
  const [broker, setBroker] = useState<BrokerId>("zerodha");

  return (
    <Gated
      permission="manageBrokerCredentials"
      fallback={
        <p className="mt-3 text-[11px] text-text-faint">
          Only a SystemAdministrator can write or remove broker credentials.
        </p>
      }
    >
      <div className="mt-3 rounded-xl border border-card-edge bg-bg p-3.5">
        <div className="flex items-center gap-2">
          <select
            value={broker}
            onChange={(e) => setBroker(e.target.value as BrokerId)}
            className="rounded-md border border-card-edge bg-panel px-2 py-1.5 text-xs text-text"
          >
            <option value="zerodha">Zerodha (Kite Connect)</option>
            <option value="upstox">Upstox</option>
          </select>
          <DeleteButton broker={broker} />
        </div>
        {broker === "zerodha" ? (
          <ZerodhaFields />
        ) : (
          <UpstoxFields />
        )}
      </div>
    </Gated>
  );
}

function DeleteButton({ broker }: { broker: BrokerId }) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api.deleteBrokerCredentials(broker),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations-status"] }),
  });
  return (
    <button
      onClick={() => remove.mutate()}
      disabled={remove.isPending}
      title={`Remove stored ${broker} credentials from Vault`}
      className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium text-text-faint transition hover:bg-down/10 hover:text-down"
    >
      <Trash2 className="h-3 w-3" /> Remove
    </button>
  );
}

function ZerodhaFields() {
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState("");
  const [accessToken, setAccessToken] = useState("");

  const write = useMutation({
    mutationFn: () =>
      api.writeBrokerCredentials("zerodha", { api_key: apiKey, access_token: accessToken }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations-status"] });
      setApiKey("");
      setAccessToken("");
    },
  });

  return (
    <CredentialFields
      fields={[
        { value: apiKey, onChange: setApiKey, placeholder: "API key" },
        { value: accessToken, onChange: setAccessToken, placeholder: "Access token" },
      ]}
      canSubmit={apiKey.trim() !== "" && accessToken.trim() !== ""}
      pending={write.isPending}
      isError={write.isError}
      onSubmit={() => write.mutate()}
    />
  );
}

function UpstoxFields() {
  const queryClient = useQueryClient();
  const [accessToken, setAccessToken] = useState("");

  const write = useMutation({
    mutationFn: () => api.writeBrokerCredentials("upstox", { access_token: accessToken }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations-status"] });
      setAccessToken("");
    },
  });

  return (
    <CredentialFields
      fields={[{ value: accessToken, onChange: setAccessToken, placeholder: "Access token" }]}
      canSubmit={accessToken.trim() !== ""}
      pending={write.isPending}
      isError={write.isError}
      onSubmit={() => write.mutate()}
    />
  );
}

function CredentialFields({
  fields,
  canSubmit,
  pending,
  isError,
  onSubmit,
}: {
  fields: { value: string; onChange: (v: string) => void; placeholder: string }[];
  canSubmit: boolean;
  pending: boolean;
  isError: boolean;
  onSubmit: () => void;
}) {
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-2">
      {fields.map((field) => (
        <input
          key={field.placeholder}
          type="password"
          value={field.value}
          onChange={(e) => field.onChange(e.target.value)}
          placeholder={field.placeholder}
          autoComplete="off"
          className="min-w-[160px] flex-1 rounded-md border border-card-edge bg-panel px-2 py-1.5 text-xs text-text placeholder:text-text-faint"
        />
      ))}
      <Button onClick={onSubmit} disabled={!canSubmit || pending} className="px-3 py-1.5 text-[11px]">
        {pending ? "Saving…" : "Save to Vault"}
      </Button>
      {isError && <p className="w-full text-[10px] text-down">Failed to write credentials.</p>}
    </div>
  );
}
