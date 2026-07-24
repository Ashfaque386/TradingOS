"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { AgentLogStreamMessage } from "@/lib/api";

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-IN", { hour12: false });
  } catch {
    return iso;
  }
}

/** Real-time terminal panel per §2.1's "Thought Stream" -- fed by the real
 * `/api/v1/stream/agents/logs` relay (src/api/routers/streams.py). This shows the honest
 * AgentLog-derived summaries the backend actually produces, not fabricated raw prompt/tool-call/
 * LLM-output content: raw LangSmith trace content isn't reachable from the backend today (no
 * local persistence, traces go straight to LangSmith's cloud UI -- see
 * src/api/routers/agents.py's module docstring). */
export function ThoughtStream({
  messages,
  connected,
}: {
  messages: AgentLogStreamMessage[];
  connected: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500">
        <span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-emerald-400" : "bg-amber-400")} />
        {connected ? "Live" : "Reconnecting…"}
      </div>
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-xl border border-white/5 bg-black/50 p-3 font-mono text-[11px] leading-relaxed"
      >
        {messages.length === 0 ? (
          <p className="text-zinc-600">
            No agent activity yet. Trigger a research cycle to see live reasoning here.
          </p>
        ) : (
          messages.map((m, i) => (
            <div key={i} className="mb-1.5 flex gap-2">
              <span className="shrink-0 text-zinc-600">{formatTime(m.ts)}</span>
              <span className="shrink-0 font-semibold text-purple-300">[{m.node}]</span>
              <span className="text-cyan-100/90">{m.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
