"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import { AlertTriangle, ChevronsRight, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { KILL_SWITCH_ROLES, useAuth } from "@/lib/auth";

const HANDLE_WIDTH = 52;
const TRACK_PADDING = 8;
const CONFIRM_THRESHOLD = 0.85;

export function KillSwitchButton() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  // Server-enforced too (src/api/routers/system.py's require_role) -- this only spares the
  // wrong role a round-trip to find out via a 403.
  const canTrigger = !!user && KILL_SWITCH_ROLES.includes(user.role);

  const { data: status } = useQuery({
    queryKey: ["kill-switch-status"],
    queryFn: api.killSwitchStatus,
    refetchInterval: 3_000,
  });

  const trip = useMutation({
    mutationFn: () =>
      api.tripKillSwitch("Manual emergency halt via Portfolio & Risk Command Center"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kill-switch-status"] }),
  });

  const reset = useMutation({
    mutationFn: api.resetKillSwitch,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["kill-switch-status"] }),
  });

  const [confirmingReset, setConfirmingReset] = useState(false);

  if (status?.state === "TRIPPED") {
    return (
      <div
        data-testid="kill-switch-tripped-banner"
        className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-5"
      >
        <div className="flex items-center gap-2 text-rose-300">
          <AlertTriangle className="h-4 w-4 animate-pulse-glow" />
          <span className="text-sm font-semibold tracking-wide">SYSTEM HALTED</span>
        </div>
        <p className="mt-1.5 text-xs text-rose-300/70">
          Tripped at{" "}
          {status.tripped_at
            ? new Date(status.tripped_at).toLocaleTimeString("en-IN", { hour12: false })
            : "—"}
        </p>

        {!canTrigger ? (
          <p data-testid="kill-switch-insufficient-role" className="mt-4 text-[11px] text-zinc-500">
            Your role ({user?.role ?? "unknown"}) cannot re-arm the system. Requires System
            Administrator, Portfolio Manager, or Risk Manager.
          </p>
        ) : !confirmingReset ? (
          <button
            data-testid="kill-switch-rearm-button"
            onClick={() => setConfirmingReset(true)}
            className="mt-4 w-full rounded-lg border border-white/10 bg-white/5 py-2 text-xs font-medium text-zinc-300 transition hover:bg-white/10"
          >
            Re-arm system
          </button>
        ) : (
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => setConfirmingReset(false)}
              className="flex-1 rounded-lg border border-white/10 py-2 text-xs text-zinc-400 transition hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                reset.mutate();
                setConfirmingReset(false);
              }}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/90 py-2 text-xs font-semibold text-black transition hover:bg-emerald-400"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Confirm re-arm
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <SlideToHalt onConfirm={() => trip.mutate()} pending={trip.isPending} disabled={!canTrigger} />
  );
}

function SlideToHalt({
  onConfirm,
  pending,
  disabled,
}: {
  onConfirm: () => void;
  pending: boolean;
  disabled: boolean;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const x = useMotionValue(0);
  const glow = useTransform(x, [0, 240], [0.12, 0.85]);
  const [triggered, setTriggered] = useState(false);
  const locked = pending || triggered || disabled;

  const handleDragEnd = () => {
    const track = trackRef.current;
    if (!track) return;
    const maxDrag = track.clientWidth - HANDLE_WIDTH - TRACK_PADDING * 2;
    if (x.get() >= maxDrag * CONFIRM_THRESHOLD) {
      setTriggered(true);
      animate(x, maxDrag, { duration: 0.15 });
      onConfirm();
    } else {
      animate(x, 0, { type: "spring", stiffness: 420, damping: 32 });
    }
  };

  return (
    <div
      data-testid="kill-switch-armed-panel"
      className="rounded-2xl border border-rose-500/20 bg-gradient-to-b from-rose-500/[0.07] to-transparent p-5"
    >
      <div className="mb-3 flex items-center gap-2 text-zinc-300">
        <AlertTriangle className="h-4 w-4 text-rose-400" />
        <span className="text-sm font-semibold tracking-wide">EMERGENCY HALT</span>
      </div>
      <p className="mb-4 text-[11px] leading-relaxed text-zinc-500">
        Cancels every open order and liquidates all positions across every connected broker.
      </p>
      <div
        ref={trackRef}
        data-testid="kill-switch-track"
        className="relative h-14 w-full overflow-hidden rounded-full border border-rose-500/25 bg-black/40"
      >
        <motion.div className="pointer-events-none absolute inset-0 bg-rose-500/20" style={{ opacity: glow }} />
        <div className="absolute inset-0 flex items-center justify-center text-xs font-medium uppercase tracking-[0.2em] text-rose-300/60">
          {pending
            ? "Halting…"
            : triggered
              ? "Confirmed"
              : disabled
                ? "Insufficient role"
                : "Slide to confirm"}
        </div>
        <motion.div
          data-testid="kill-switch-slider"
          drag={locked ? false : "x"}
          dragConstraints={trackRef}
          dragElastic={0.04}
          dragMomentum={false}
          onDragEnd={handleDragEnd}
          style={{ x, width: HANDLE_WIDTH, left: TRACK_PADDING, top: TRACK_PADDING }}
          className="absolute flex h-12 cursor-grab items-center justify-center rounded-full bg-rose-500 text-black shadow-[0_0_20px_rgba(251,113,133,0.55)] active:cursor-grabbing"
        >
          <ChevronsRight className="h-5 w-5" />
        </motion.div>
      </div>
    </div>
  );
}
