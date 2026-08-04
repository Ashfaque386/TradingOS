"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { RequireAuth } from "@/lib/auth";
import { Sidebar } from "@/components/layout/sidebar";
import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { IntegrationStatusGrid } from "@/components/settings/integration-status-grid";
import { NotificationChannels } from "@/components/settings/notification-channels";
import { BrokerCredentialsForm } from "@/components/settings/broker-credentials-form";
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
            <Card eyebrow="LLM Providers" title="API Key Management">
              {integrationsQuery.data ? (
                <IntegrationStatusGrid items={integrationsQuery.data.llm_providers} />
              ) : (
                <div className="h-24 animate-pulse rounded-xl bg-bg" />
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-text-faint">
                Read-only: keys are loaded from <code className="text-text-dim">.env</code> once at
                process start and are never returned in full. To change a key, edit{" "}
                <code className="text-text-dim">.env</code> and restart the app.
              </p>
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
