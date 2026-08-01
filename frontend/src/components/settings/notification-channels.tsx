"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ALERT_LEVELS, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Gated } from "@/components/ui/gated";
import type { AlertLevel, ChannelType, NotificationChannel } from "@/lib/api";

const CHANNEL_TYPES: ChannelType[] = ["Telegram", "Discord", "WhatsApp", "Slack", "Email"];

const ALERT_LABELS: Record<AlertLevel, string> = {
  critical_errors: "Critical errors",
  executed_trades: "Executed trades",
  risk_warnings: "Risk warnings",
  strategy_promotions: "Strategy promotions",
};

export function NotificationChannels() {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);

  const channelsQuery = useQuery({
    queryKey: ["notification-channels"],
    queryFn: api.notificationChannels,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteNotificationChannel(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notification-channels"] }),
  });

  const toggleAlertLevel = useMutation({
    mutationFn: ({ channel, level }: { channel: NotificationChannel; level: AlertLevel }) => {
      const current = channel.preferences.alert_levels ?? [];
      const next = current.includes(level)
        ? current.filter((l) => l !== level)
        : [...current, level];
      return api.updateNotificationChannel(channel.id, { alert_levels: next });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notification-channels"] }),
  });

  const channels = channelsQuery.data ?? [];

  return (
    <div className="space-y-3">
      {channels.length === 0 && !adding && (
        <p className="text-xs text-zinc-500">
          No notification channels configured. Add one to route alerts to Telegram, Discord, and
          more.
        </p>
      )}

      {channels.map((channel) => (
        <div key={channel.id} className="rounded-xl border border-white/5 bg-black/20 p-3.5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
                {channel.channel_type}
              </span>
              <span className="font-mono-tabular text-xs text-zinc-300">
                {channel.external_handle}
              </span>
              {channel.is_verified && (
                <span className="flex items-center gap-1 text-[10px] text-emerald-300">
                  <BadgeCheck className="h-3 w-3" /> Verified
                </span>
              )}
            </div>
            <Gated permission="manageNotificationChannels">
              <button
                onClick={() => remove.mutate(channel.id)}
                disabled={remove.isPending}
                className="rounded-md p-1.5 text-zinc-600 transition hover:bg-rose-500/10 hover:text-rose-400"
                aria-label="Remove channel"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </Gated>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {ALERT_LEVELS.map((level) => {
              const active = (channel.preferences.alert_levels ?? []).includes(level);
              const pill = (
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
                    active
                      ? "bg-cyan-400/15 text-cyan-200"
                      : "bg-white/5 text-zinc-600",
                  )}
                >
                  {ALERT_LABELS[level]}
                </span>
              );
              return (
                <Gated key={level} permission="manageNotificationChannels" fallback={pill}>
                  <button
                    onClick={() => toggleAlertLevel.mutate({ channel, level })}
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
                      active
                        ? "bg-cyan-400/15 text-cyan-200"
                        : "bg-white/5 text-zinc-600 hover:text-zinc-400",
                    )}
                  >
                    {ALERT_LABELS[level]}
                  </button>
                </Gated>
              );
            })}
          </div>
        </div>
      ))}

      <Gated permission="manageNotificationChannels">
        {adding ? (
          <AddChannelForm onDone={() => setAdding(false)} />
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-dashed border-white/10 py-2.5 text-xs font-medium text-zinc-500 transition hover:border-white/20 hover:text-zinc-300"
          >
            <Plus className="h-3.5 w-3.5" /> Add channel
          </button>
        )}
      </Gated>
    </div>
  );
}

function AddChannelForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [channelType, setChannelType] = useState<ChannelType>("Telegram");
  const [handle, setHandle] = useState("");
  const [levels, setLevels] = useState<AlertLevel[]>([]);

  const create = useMutation({
    mutationFn: () =>
      api.createNotificationChannel({
        channel_type: channelType,
        external_handle: handle,
        alert_levels: levels,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
      onDone();
    },
  });

  return (
    <div className="rounded-xl border border-cyan-400/20 bg-cyan-400/[0.03] p-3.5">
      <div className="flex flex-wrap gap-2">
        <select
          value={channelType}
          onChange={(e) => setChannelType(e.target.value as ChannelType)}
          className="rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-zinc-200"
        >
          {CHANNEL_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          placeholder="Chat ID, webhook, or address"
          className="min-w-[180px] flex-1 rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600"
        />
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {ALERT_LEVELS.map((level) => (
          <button
            key={level}
            onClick={() =>
              setLevels((prev) =>
                prev.includes(level) ? prev.filter((l) => l !== level) : [...prev, level],
              )
            }
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
              levels.includes(level)
                ? "bg-cyan-400/15 text-cyan-200"
                : "bg-white/5 text-zinc-600 hover:text-zinc-400",
            )}
          >
            {ALERT_LABELS[level]}
          </button>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <button
          onClick={onDone}
          className="flex-1 rounded-lg border border-white/10 py-1.5 text-[11px] text-zinc-400 hover:bg-white/5"
        >
          Cancel
        </button>
        <button
          onClick={() => create.mutate()}
          disabled={!handle.trim() || create.isPending}
          className="flex-1 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-500 py-1.5 text-[11px] font-semibold text-black transition hover:brightness-110 disabled:opacity-40"
        >
          {create.isPending ? "Adding…" : "Add channel"}
        </button>
      </div>
      {create.isError && (
        <p className="mt-2 text-[10px] text-rose-400">Failed to add channel. Check the handle format.</p>
      )}
    </div>
  );
}
