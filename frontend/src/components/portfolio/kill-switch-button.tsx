"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import { AlertTriangle, ChevronsRight, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { KILL_SWITCH_ROLES, useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { scaleIn } from "@/lib/motion";

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
        className="rounded-card border border-down/30 bg-down/10 p-5 sm:p-6"
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 shrink-0 animate-pulse-glow text-down" />
            <div>
              <span className="text-sm font-semibold tracking-wide text-down">SYSTEM HALTED</span>
              <p className="mt-0.5 text-xs text-down/70">
                Tripped at{" "}
                {status.tripped_at
                  ? new Date(status.tripped_at).toLocaleTimeString("en-IN", { hour12: false })
                  : "—"}
              </p>
            </div>
          </div>

          {!canTrigger ? (
            <p
              data-testid="kill-switch-insufficient-role"
              className="text-[11px] text-text-faint sm:max-w-xs sm:text-right"
            >
              Your role ({user?.role ?? "unknown"}) cannot re-arm the system. Requires System
              Administrator, Portfolio Manager, or Risk Manager.
            </p>
          ) : !confirmingReset ? (
            <Button
              data-testid="kill-switch-rearm-button"
              onClick={() => setConfirmingReset(true)}
              variant="secondary"
              className="w-full sm:w-auto"
            >
              Re-arm system
            </Button>
          ) : (
            <motion.div
              initial="hidden"
              animate="visible"
              variants={scaleIn}
              className="flex w-full gap-2 sm:w-auto"
            >
              <Button
                onClick={() => setConfirmingReset(false)}
                variant="secondary"
                className="flex-1 sm:flex-none"
              >
                Cancel
              </Button>
              <Button
                onClick={() => {
                  reset.mutate();
                  setConfirmingReset(false);
                }}
                className="flex-1 sm:flex-none"
              >
                <RotateCcw className="h-3.5 w-3.5" /> Confirm re-arm
              </Button>
            </motion.div>
          )}
        </div>
      </div>
    );
  }

  return (
    <SlideToHalt onConfirm={() => trip.mutate()} pending={trip.isPending} disabled={!canTrigger} />
  );
}

/** Assumed max drag distance for progress-linked effects (fill width, label fade, glow) --
 * matches the ~300px track width set below; the real per-render max (`handleDragEnd`'s own
 * `maxDrag`, from the track's actual measured `clientWidth`) is what the confirm threshold and
 * release-spring snap-back use, so a small mismatch here only softens the visual ramp, never the
 * real confirm behavior. */
const PROGRESS_RANGE = 232;

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
  const progress = useTransform(x, [0, PROGRESS_RANGE], [0, 1], { clamp: true });
  const fillWidth = useTransform(progress, (p) => `${p * 100}%`);
  const labelOpacity = useTransform(progress, [0, 1], [0.55, 1]);
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
      className="rounded-card border border-down/20 bg-gradient-to-b from-down/[0.07] to-transparent p-5 sm:p-6"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 shrink-0 text-down" />
          <div>
            <span className="text-sm font-semibold tracking-wide text-text-dim">
              EMERGENCY HALT
            </span>
            <p className="mt-0.5 text-[11px] leading-relaxed text-text-faint sm:max-w-xs">
              Cancels every open order and liquidates all positions across every connected broker.
            </p>
          </div>
        </div>

        <div
          ref={trackRef}
          data-testid="kill-switch-track"
          className="relative h-14 w-full shrink-0 overflow-hidden rounded-full border border-down/25 bg-bg shadow-[inset_0_1px_3px_rgba(0,0,0,0.06)] sm:w-[300px]"
        >
          {/* Real drag-progress fill, not a flat opacity wash -- grows with the handle so the
              track itself communicates how close the drag is to confirming, matching the
              slide-to-pay pattern used by real payment/exchange confirm sliders. */}
          <motion.div
            className="pointer-events-none absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-down/20 to-down/35"
            style={{ width: fillWidth }}
          />
          <motion.div
            className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs font-medium uppercase tracking-[0.2em] text-down/70"
            style={{ opacity: locked ? 1 : labelOpacity }}
          >
            {pending
              ? "Halting…"
              : triggered
                ? "Confirmed"
                : disabled
                  ? "Insufficient role"
                  : "Slide to confirm"}
          </motion.div>
          <motion.div
            data-testid="kill-switch-slider"
            drag={locked ? false : "x"}
            dragConstraints={trackRef}
            dragElastic={0.04}
            dragMomentum={false}
            onDragEnd={handleDragEnd}
            animate={!locked ? { scale: [1, 1.05, 1] } : { scale: 1 }}
            transition={!locked ? { duration: 2.4, repeat: Infinity, ease: "easeInOut" } : undefined}
            style={{ x, top: "50%", y: "-50%", width: HANDLE_WIDTH, left: TRACK_PADDING }}
            className="absolute flex h-12 cursor-grab items-center justify-center rounded-full bg-gradient-to-b from-down to-down/90 text-white shadow-[0_2px_10px_rgba(244,63,94,0.45),0_0_20px_rgba(244,63,94,0.4)] ring-1 ring-white/20 active:cursor-grabbing"
          >
            <ChevronsRight className="h-5 w-5" />
          </motion.div>
        </div>
      </div>
    </div>
  );
}
