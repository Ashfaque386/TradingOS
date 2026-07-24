"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useChatMessages } from "@/hooks/useChatMessages";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", { hour12: false });
}

export function ChatPanel() {
  const { messages, hasPendingReply } = useChatMessages();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const send = useMutation({
    mutationFn: (content: string) => api.sendChatMessage(content),
    onSuccess: () => {
      setDraft("");
      queryClient.invalidateQueries({ queryKey: ["chat-messages"] });
    },
  });

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  const canSend = draft.trim().length > 0 && !hasPendingReply && !send.isPending;

  return (
    <div className="flex h-full flex-col">
      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-white/5 bg-black/30 p-4"
      >
        {messages.length === 0 && (
          <p className="text-xs text-zinc-600">
            No messages yet. Ask the CEO Agent about current risk, strategy status, or the kill
            switch — it answers from real system state, not a script.
          </p>
        )}
        {messages.map((m) => (
          <motion.div
            key={m.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
          >
            <div
              className={cn(
                "max-w-[80%] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed",
                m.role === "user"
                  ? "bg-gradient-to-br from-cyan-500/90 to-purple-500/90 text-black"
                  : "glass-panel border-purple-400/20 text-zinc-200 shadow-[0_0_20px_rgba(167,139,250,0.08)]",
              )}
            >
              {m.role === "assistant" && m.status === "Pending" && (
                <span className="flex items-center gap-1.5 text-purple-300">
                  <span className="flex gap-0.5">
                    <span className="h-1 w-1 animate-pulse-glow rounded-full bg-purple-400" />
                    <span
                      className="h-1 w-1 animate-pulse-glow rounded-full bg-purple-400"
                      style={{ animationDelay: "0.2s" }}
                    />
                    <span
                      className="h-1 w-1 animate-pulse-glow rounded-full bg-purple-400"
                      style={{ animationDelay: "0.4s" }}
                    />
                  </span>
                  Thinking — real LLM calls can take several minutes in this environment
                </span>
              )}
              {m.role === "assistant" && m.status === "Failed" && (
                <span className="text-rose-400">Reply failed: {m.error}</span>
              )}
              {(m.role === "user" || m.status === "Completed") && (
                <span className="whitespace-pre-wrap">{m.content}</span>
              )}
              <div
                className={cn(
                  "mt-1 text-[9px] opacity-60",
                  m.role === "user" ? "text-black/70" : "text-zinc-500",
                )}
              >
                {formatTime(m.created_at)}
              </div>
            </div>
          </motion.div>
        ))}
      </div>

      <div className="mt-3 flex gap-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) send.mutate(draft.trim());
            }
          }}
          placeholder={
            hasPendingReply ? "Waiting for the current reply to finish…" : "Message the CEO Agent…"
          }
          rows={2}
          disabled={hasPendingReply}
          className="flex-1 resize-none rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-cyan-400/40 focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={() => canSend && send.mutate(draft.trim())}
          disabled={!canSend}
          className="flex items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500 to-purple-500 px-4 text-black transition hover:brightness-110 disabled:opacity-40"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
