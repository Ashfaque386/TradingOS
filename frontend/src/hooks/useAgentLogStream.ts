"use client";

import { useEffect, useRef, useState } from "react";
import { WS_BASE, type AgentLogStreamMessage } from "@/lib/api";

const MAX_BUFFERED = 200;

/** Thought Stream feed (API-092, `/stream/agents/logs`). Buffers incoming frames in a ref and
 * flushes into React state at most once per animation frame, same throttling pattern as
 * usePortfolioSocket -- per Phase_7_Frontend_Architecture.md §4. */
export function useAgentLogStream(): {
  logs: AgentLogStreamMessage[];
  connected: boolean;
} {
  const [logs, setLogs] = useState<AgentLogStreamMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const bufferRef = useRef<AgentLogStreamMessage[]>([]);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const scheduleFlush = () => {
      if (frameRef.current !== null) return;
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        setLogs((prev) => [...prev, ...bufferRef.current].slice(-MAX_BUFFERED));
        bufferRef.current = [];
      });
    };

    const connect = () => {
      if (cancelled) return;
      socket = new WebSocket(`${WS_BASE}/api/v1/stream/agents/logs`);

      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        bufferRef.current.push(JSON.parse(event.data) as AgentLogStreamMessage);
        scheduleFlush();
      };
      socket.onclose = () => {
        setConnected(false);
        if (!cancelled) retryTimer = setTimeout(connect, 3_000);
      };
      socket.onerror = () => socket?.close();
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      socket?.close();
    };
  }, []);

  return { logs, connected };
}
