"use client";

import { RequireAuth } from "@/lib/auth";
import { Sidebar } from "@/components/layout/sidebar";
import { PageHeader } from "@/components/layout/page-header";
import { GlassCard } from "@/components/ui/glass-card";
import { ChatPanel } from "@/components/chat/chat-panel";
import { LiveCanvas } from "@/components/chat/live-canvas";

export default function ChatPage() {
  return (
    <RequireAuth>
      <div className="flex flex-1">
        <Sidebar />
        <div className="flex flex-1 flex-col">
          <PageHeader connected subtitle="Omni-Channel Chat & Live Canvas" />

          <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-12 xl:items-stretch">
              <GlassCard eyebrow="Conversation" title="CEO Agent" className="flex flex-col xl:col-span-6">
                <div className="h-[560px]">
                  <ChatPanel />
                </div>
              </GlassCard>

              <div className="xl:col-span-6">
                <div className="h-[560px]">
                  <LiveCanvas />
                </div>
              </div>
            </div>
          </main>
        </div>
      </div>
    </RequireAuth>
  );
}
