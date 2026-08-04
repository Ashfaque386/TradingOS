"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

const ARC_START = -120;
const ARC_END = 120;
const RADIUS = 70;
const ARC_PATH = describeFullArc();
const ARC_LENGTH = (Math.PI * RADIUS * (ARC_END - ARC_START)) / 180;

function polarToCartesian(angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: 90 + RADIUS * Math.cos(rad), y: 90 + RADIUS * Math.sin(rad) };
}

function describeFullArc() {
  const start = polarToCartesian(ARC_END);
  const end = polarToCartesian(ARC_START);
  return `M ${start.x} ${start.y} A ${RADIUS} ${RADIUS} 0 1 0 ${end.x} ${end.y}`;
}

export interface RiskGaugeProps {
  label: string;
  value: number | null;
  min: number;
  max: number;
  displayValue: string;
  unavailableReason?: string;
  colorVar?: string;
  subtext?: string;
}

/** Semicircle-ish arc gauge, per §2.2 "Risk Metrics: Real-time gauge components." When `value`
 * is null (e.g. Beta vs Nifty 50 -- no live equity curve exists yet, see portfolio.py's
 * docstring) it renders an honest dashed "no data" arc instead of a fake reading. */
export function RiskGauge({
  label,
  value,
  min,
  max,
  displayValue,
  unavailableReason,
  colorVar = "var(--color-brand-via)",
  subtext,
}: RiskGaugeProps) {
  const clamped = value === null ? null : Math.min(max, Math.max(min, value));
  const pct = clamped === null ? 0 : (clamped - min) / (max - min);

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 180 110" className="w-full max-w-[190px]">
        <path
          d={ARC_PATH}
          fill="none"
          stroke="var(--card-edge)"
          strokeWidth={10}
          strokeLinecap="round"
        />
        {value !== null ? (
          <motion.path
            d={ARC_PATH}
            fill="none"
            stroke={colorVar}
            strokeWidth={10}
            strokeLinecap="round"
            strokeDasharray={ARC_LENGTH}
            initial={{ strokeDashoffset: ARC_LENGTH }}
            animate={{ strokeDashoffset: ARC_LENGTH * (1 - pct) }}
            transition={{ duration: 0.9, ease: "easeOut" }}
            style={{ filter: `drop-shadow(0 0 6px ${colorVar})` }}
          />
        ) : (
          <path
            d={ARC_PATH}
            fill="none"
            stroke="var(--text-faint)"
            strokeWidth={10}
            strokeDasharray="2 6"
            strokeLinecap="round"
            opacity={0.4}
          />
        )}
        <text
          x="90"
          y="80"
          textAnchor="middle"
          className="font-mono-tabular"
          fill={value === null ? "var(--text-faint)" : "var(--text)"}
          fontSize="22"
          fontFamily="var(--font-mono)"
          fontWeight={600}
        >
          {value === null ? "—" : displayValue}
        </text>
      </svg>
      <div className="-mt-1 text-center">
        <div className="text-xs font-medium uppercase tracking-wider text-text-dim">{label}</div>
        <div className={cn("mt-0.5 text-[11px]", value === null ? "text-text-faint" : "text-text-dim")}>
          {value === null ? (unavailableReason ?? "No data") : subtext}
        </div>
      </div>
    </div>
  );
}
