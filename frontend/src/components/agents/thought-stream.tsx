"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AgentLogStreamMessage } from "@/lib/api";

const ALL = "__all__";

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
 * src/api/routers/agents.py's module docstring).
 *
 * Phase 2C: filter-by-agent and filter-by-node added -- both fields are already present on every
 * `AgentLogStreamMessage`, so this is real filtering, not a cosmetic control. Severity/level
 * filtering deliberately NOT added: the live WS payload has no `log_level` field (unlike the
 * REST-side `AgentLogEntry` this stream doesn't use), so there's nothing real to filter by. */
export function ThoughtStream({
  messages,
  connected,
}: {
  messages: AgentLogStreamMessage[];
  connected: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [agentFilter, setAgentFilter] = useState(ALL);
  const [nodeFilter, setNodeFilter] = useState(ALL);
  const [search, setSearch] = useState("");

  const agentOptions = useMemo(
    () => [...new Set(messages.map((m) => m.agent_id))].sort(),
    [messages],
  );
  const nodeOptions = useMemo(
    () => [...new Set(messages.map((m) => m.node))].sort(),
    [messages],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return messages.filter(
      (m) =>
        (agentFilter === ALL || m.agent_id === agentFilter) &&
        (nodeFilter === ALL || m.node === nodeFilter) &&
        (q === "" || m.message.toLowerCase().includes(q)),
    );
  }, [messages, agentFilter, nodeFilter, search]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [filtered.length]);

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-text-faint">
          <span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-up" : "bg-warn")} />
          {connected ? "Live" : "Reconnecting…"}
        </div>
        <span className="font-mono-tabular text-[10px] text-text-faint">
          {filtered.length} / {messages.length}
        </span>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <div className="relative flex-1 min-w-[120px]">
          <Search className="pointer-events-none absolute top-1/2 left-2 h-3 w-3 -translate-y-1/2 text-text-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search messages…"
            className="w-full rounded-md border border-card-edge bg-bg py-1 pr-2 pl-6 text-[10px] text-text placeholder:text-text-faint"
          />
        </div>
        <Select value={agentFilter} onValueChange={(v) => setAgentFilter(v as string)}>
          <SelectTrigger size="sm" className="text-[10px]">
            <SelectValue placeholder="Agent" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All agents</SelectItem>
            {agentOptions.map((a) => (
              <SelectItem key={a} value={a}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={nodeFilter} onValueChange={(v) => setNodeFilter(v as string)}>
          <SelectTrigger size="sm" className="text-[10px]">
            <SelectValue placeholder="Node" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All nodes</SelectItem>
            {nodeOptions.map((n) => (
              <SelectItem key={n} value={n}>
                {n}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-xl border border-card-edge bg-bg p-3 font-mono text-[11px] leading-relaxed"
      >
        {messages.length === 0 ? (
          <p className="text-text-faint">
            No agent activity yet. Trigger a research cycle to see live reasoning here.
          </p>
        ) : filtered.length === 0 ? (
          <p className="text-text-faint">No messages match the current filters.</p>
        ) : (
          filtered.map((m, i) => (
            <div key={i} className="mb-1.5 flex gap-2">
              <span className="shrink-0 text-text-faint">{formatTime(m.ts)}</span>
              <span className="shrink-0 font-semibold text-brand-via">[{m.node}]</span>
              <span className="text-text-dim">{m.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
