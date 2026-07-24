"use client";

import { useEffect, useRef, useState } from "react";
import { WS_BASE, type PortfolioTick } from "@/lib/api";

/** Live portfolio ticker (API-094). Incoming frames are buffered in a ref and flushed into React
 * state at most once per animation frame -- per Phase_7_Frontend_Architecture.md §4's "max 60fps
 * DOM updates" rule, so a burst of WS messages can never trigger more re-renders than the
 * browser can actually paint. */
export function usePortfolioSocket(): {
  tick: PortfolioTick | null;
  connected: boolean;
} {
  const [tick, setTick] = useState<PortfolioTick | null>(null);
  const [connected, setConnected] = useState(false);
  const latestRef = useRef<PortfolioTick | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const scheduleFlush = () => {
      if (frameRef.current !== null) return;
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        if (latestRef.current) setTick(latestRef.current);
      });
    };

    const connect = () => {
      if (cancelled) return;
      socket = new WebSocket(`${WS_BASE}/api/v1/stream/portfolio`);

      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        latestRef.current = JSON.parse(event.data) as PortfolioTick;
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

  return { tick, connected };
}
