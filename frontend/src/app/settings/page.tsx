"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { Sidebar } from "@/components/layout/sidebar";
import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { AppearanceToggle } from "@/components/settings/appearance-toggle";
import { IntegrationStatusGrid } from "@/components/settings/integration-status-grid";
import { NotificationChannels } from "@/components/settings/notification-channels";
import { BrokerCredentialsForm } from "@/components/settings/broker-credentials-form";
import { LlmProviderKeyForm } from "@/components/settings/llm-provider-key-form";
import { RiskLimitsPanel } from "@/components/settings/risk-limits-panel";

export default function SettingsPage() {
  const integrationsQuery = useQuery({
    queryKey: ["integrations-status"],
    queryFn: api.integrationsStatus,
  });

  return (
    <RequireAuth>
      <div className="flex flex-1">
        <Sidebar />
        <div className="flex flex-1 flex-col">
          <PageHeader connected={integrationsQuery.isSuccess} subtitle="Global Settings & Integrations" />

          <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
            <Card eyebrow="Preferences" title="Appearance">
              <p className="mb-3 text-[11px] leading-relaxed text-text-faint">
                Both modes are variants of the same design -- there is no separate accent picker
                to choose (retired with the 2026-08-01 direction). Takes effect immediately,
                persists across reloads, and needs no page refresh.
              </p>
              <AppearanceToggle />
            </Card>

            <Card eyebrow="LLM Providers" title="API Key Management">
              {integrationsQuery.data ? (
                <IntegrationStatusGrid items={integrationsQuery.data.llm_providers} />
              ) : (
                <div className="h-24 animate-pulse rounded-xl bg-bg" />
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-text-faint">
                Keys live in Vault, never in this database — the status above never exposes a
                stored value, only whether each provider is wired up. Writing a new value below
                (REL-021 E21.1) is write-only in the same way: there is no endpoint anywhere in
                this codebase that reads a stored key back out. Takes effect on the very next LLM
                call, no restart needed.
              </p>
              <LlmProviderKeyForm />
            </Card>

            <Card eyebrow="Execution" title="Broker Configuration">
              {integrationsQuery.data ? (
                <IntegrationStatusGrid items={integrationsQuery.data.brokers} />
              ) : (
                <div className="h-16 animate-pulse rounded-xl bg-bg" />
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-text-faint">
                Broker credentials live in Vault, never in this database (see DB-004) — the status
                above never exposes a stored value, only whether each broker is wired up. Writing a
                new value below (REL-017 E17.2) is write-only in the same way: there is no endpoint
                anywhere in this codebase that reads a stored credential back out to an API client.
              </p>
              <BrokerCredentialsForm />
            </Card>

            <Card eyebrow="Risk" title="Risk Limits">
              <RiskLimitsPanel />
            </Card>

            <Card eyebrow="Alerting" title="Notification Channels">
              <NotificationChannels />
            </Card>
          </main>
        </div>
      </div>
    </RequireAuth>
  );
}
