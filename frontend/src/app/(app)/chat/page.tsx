"use client";

import { usePageStatus } from "@/hooks/usePageStatus";
import { Card } from "@/components/ui/card";
import { ChatPanel } from "@/components/chat/chat-panel";
import { LiveCanvas } from "@/components/chat/live-canvas";

export default function ChatPage() {
  usePageStatus("Omni-Channel Chat & Live Canvas", true);

  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12 xl:items-stretch">
        <Card eyebrow="Conversation" title="CEO Agent" className="flex flex-col xl:col-span-6">
          <div className="h-[560px]">
            <ChatPanel />
          </div>
        </Card>

        <div className="xl:col-span-6">
          <div className="h-[560px]">
            <LiveCanvas />
          </div>
        </div>
      </div>
    </main>
  );
}
