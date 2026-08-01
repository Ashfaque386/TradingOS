"use client";

import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "@/lib/api";

export interface MarketTick {
  symbol: string;
  ltp: number;
  volume: number;
  ts: string | null;
}

/** Live tick stream for one symbol (API-091), mirroring usePortfolioSocket.ts's rAF-throttled-
 * flush + reconnect-with-backoff + cleanup conventions -- parameterized by `symbol` (re-
 * subscribes when it changes) and a no-op when `symbol` is null (no chart mounted/selected
 * yet). */
export function useMarketStream(symbol: string | null): {
  tick: MarketTick | null;
  connected: boolean;
} {
  const [tick, setTick] = useState<MarketTick | null>(null);
  const [connected, setConnected] = useState(false);
  const latestRef = useRef<MarketTick | null>(null);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (!symbol) return; // nothing to connect to -- tick/connected already at their defaults

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
      socket = new WebSocket(`${WS_BASE}/api/v1/stream/market/${symbol}`);

      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        latestRef.current = JSON.parse(event.data) as MarketTick;
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
      // Reset on symbol change/unmount so a stale tick from the previous symbol never lingers.
      setTick(null);
      setConnected(false);
    };
  }, [symbol]);

  return { tick, connected };
}
