"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, WS_BASE, type OrgEvent } from "@/lib/api";

const MAX_BUFFERED = 400;

/** US5 (FR-088/090). One multiplexed WebSocket subscription for the Organization Command
 * Center, keyed by the selected run id(s). Every `OrganizationalEvent` frame:
 *   1. is appended to a bounded local buffer the ActivityStream / RunReplay read, and
 *   2. invalidates the React Query caches for the affected run so every panel re-syncs.
 * On reconnect the hook backfills anything missed via
 * `GET /organization/runs/{id}/events?after_sequence=<lastSeen>` before resuming the live feed,
 * so a dropped socket never loses events (contracts/websocket.md). */
export function useOrganizationStream(runIds: string[]): {
  connected: boolean;
  events: OrgEvent[];
} {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<OrgEvent[]>([]);
  const queryClient = useQueryClient();

  const lastSeqRef = useRef<Map<string, number>>(new Map());
  const bufferRef = useRef<OrgEvent[]>([]);
  const frameRef = useRef<number | null>(null);
  const key = runIds.slice().sort().join(",");

  useEffect(() => {
    if (runIds.length === 0) return;
    // Fresh subscription (run set changed) -> drop the previous run's buffer. Deferred so it
    // isn't a synchronous setState inside the effect body.
    queueMicrotask(() => setEvents([]));
    lastSeqRef.current = new Map();
    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const flush = () => {
      if (frameRef.current !== null) return;
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        const batch = bufferRef.current;
        bufferRef.current = [];
        if (batch.length === 0) return;
        setEvents((prev) => [...prev, ...batch].slice(-MAX_BUFFERED));
        const touched = new Set(batch.map((e) => e.subject_id).filter(Boolean));
        void touched;
        for (const runId of runIds) {
          for (const suffix of [
            "org-run",
            "org-tasks",
            "org-dependencies",
            "org-artefacts",
            "org-decisions",
            "org-events",
          ]) {
            queryClient.invalidateQueries({ queryKey: [suffix, runId] });
          }
        }
        queryClient.invalidateQueries({ queryKey: ["org-attention"] });
        queryClient.invalidateQueries({ queryKey: ["org-approvals"] });
      });
    };

    const ingest = (e: OrgEvent, runId: string) => {
      const seen = lastSeqRef.current.get(runId) ?? 0;
      if (e.sequence <= seen) return;
      lastSeqRef.current.set(runId, e.sequence);
      bufferRef.current.push(e);
      flush();
    };

    const backfill = async () => {
      for (const runId of runIds) {
        try {
          const missed = await api.orgEvents(runId, lastSeqRef.current.get(runId) ?? 0);
          for (const e of missed) ingest(e, runId);
        } catch {
          /* a backfill hiccup is non-fatal; the live feed resumes regardless */
        }
      }
    };

    const connect = () => {
      if (cancelled) return;
      const qs = runIds.map((r) => `run_id=${encodeURIComponent(r)}`).join("&");
      socket = new WebSocket(`${WS_BASE}/api/v1/stream/organization?${qs}`);

      socket.onopen = () => {
        setConnected(true);
        void backfill();
      };
      socket.onmessage = (evt) => {
        try {
          const frame = JSON.parse(evt.data) as OrgEvent & { run_id?: string };
          const runId = frame.run_id ?? runIds[0];
          if (runIds.includes(runId)) ingest(frame, runId);
        } catch {
          /* ignore a malformed frame */
        }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { connected, events };
}
