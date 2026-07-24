"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** Polls faster while a reply is in flight -- real LLM calls in this environment can take
 * minutes (see src/api/routers/chat.py's module docstring), so this isn't a snappy websocket,
 * just an honest "keep checking" loop that backs off once nothing is Pending. */
export function useChatMessages() {
  const query = useQuery({
    queryKey: ["chat-messages"],
    queryFn: api.chatMessages,
    refetchInterval: (q) => {
      const messages = q.state.data ?? [];
      const hasPending = messages.some((m) => m.status === "Pending");
      return hasPending ? 3_000 : 15_000;
    },
  });

  return {
    ...query,
    messages: query.data ?? [],
    hasPendingReply: (query.data ?? []).some((m) => m.status === "Pending"),
  };
}
