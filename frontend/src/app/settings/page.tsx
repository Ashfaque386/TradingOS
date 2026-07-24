"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { TopBar } from "@/components/layout/top-bar";
import { GlassCard } from "@/components/ui/glass-card";
import { IntegrationStatusGrid } from "@/components/settings/integration-status-grid";
import { NotificationChannels } from "@/components/settings/notification-channels";

export default function SettingsPage() {
  const integrationsQuery = useQuery({
    queryKey: ["integrations-status"],
    queryFn: api.integrationsStatus,
  });

  return (
    <RequireAuth>
      <TopBar connected={integrationsQuery.isSuccess} subtitle="Global Settings & Integrations" />

      <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
        <GlassCard eyebrow="LLM Providers" title="API Key Management">
          {integrationsQuery.data ? (
            <IntegrationStatusGrid items={integrationsQuery.data.llm_providers} />
          ) : (
            <div className="h-24 animate-pulse rounded-xl bg-white/5" />
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
            Read-only: keys are loaded from <code className="text-zinc-500">.env</code> once at
            process start and are never returned in full. To change a key, edit{" "}
            <code className="text-zinc-500">.env</code> and restart the app.
          </p>
        </GlassCard>

        <GlassCard eyebrow="Execution" title="Broker Configuration">
          {integrationsQuery.data ? (
            <IntegrationStatusGrid items={integrationsQuery.data.brokers} />
          ) : (
            <div className="h-16 animate-pulse rounded-xl bg-white/5" />
          )}
          <p className="mt-3 text-[11px] leading-relaxed text-zinc-600">
            Broker credentials are designed to live in Vault, never in this database or API (see
            DB-004) — no key material is ever exposed here, only whether each broker is wired up.
          </p>
        </GlassCard>

        <GlassCard eyebrow="Alerting" title="Notification Channels">
          <NotificationChannels />
        </GlassCard>
      </main>
    </RequireAuth>
  );
}
