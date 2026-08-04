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
        className="flex-1 space-y-3 overflow-y-auto rounded-xl border border-card-edge bg-bg p-4"
      >
        {messages.length === 0 && (
          <p className="text-xs text-text-faint">
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
                  ? "bg-brand-gradient text-white"
                  : "border border-card-edge bg-panel text-text-dim shadow-card",
              )}
            >
              {m.role === "assistant" && m.status === "Pending" && (
                <span className="flex items-center gap-1.5 text-brand-via">
                  <span className="flex gap-0.5">
                    <span className="h-1 w-1 animate-pulse-glow rounded-full bg-brand-via" />
                    <span
                      className="h-1 w-1 animate-pulse-glow rounded-full bg-brand-via"
                      style={{ animationDelay: "0.2s" }}
                    />
                    <span
                      className="h-1 w-1 animate-pulse-glow rounded-full bg-brand-via"
                      style={{ animationDelay: "0.4s" }}
                    />
                  </span>
                  Thinking — real LLM calls can take several minutes in this environment
                </span>
              )}
              {m.role === "assistant" && m.status === "Failed" && (
                <span className="text-down">Reply failed: {m.error}</span>
              )}
              {(m.role === "user" || m.status === "Completed") && (
                <span className="whitespace-pre-wrap">{m.content}</span>
              )}
              <div
                className={cn(
                  "mt-1 text-[9px] opacity-60",
                  m.role === "user" ? "text-white/70" : "text-text-faint",
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
          className="flex-1 resize-none rounded-xl border border-card-edge bg-bg px-3 py-2 text-xs text-text placeholder:text-text-faint focus:border-brand-via focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={() => canSend && send.mutate(draft.trim())}
          disabled={!canSend}
          className="bg-brand-gradient flex items-center justify-center rounded-xl px-4 text-white transition hover:brightness-110 disabled:opacity-40"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
