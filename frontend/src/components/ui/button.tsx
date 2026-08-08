import { forwardRef } from "react";
import { cn } from "@/lib/utils";

// REL-012 Phase B (2026-08-04): the new button primitive per Phase_7_Frontend_Architecture.md
// §1.1 -- no shared Button component existed anywhere in this codebase before this (every
// button across every page is hand-rolled Tailwind, confirmed by grep). `destructive` is a new
// variant this codebase's old single-accent-color system never needed: the Kill Switch, Agent
// Registry's Disable action, and HITL Reject all currently render with the same "just another
// button" treatment (cyan/violet gradient, or a bespoke rose className, inconsistently) --
// Phase D's per-page migration should route every one of those call sites through
// `variant="destructive"` specifically, never `primary`, so a safety-critical action never
// looks like a routine positive CTA. Real call sites identified for that Phase D pass:
// `components/agents/hitl-panel.tsx` (Approve -> primary, Reject -> destructive),
// `components/agents/agent-registry.tsx` (Disable/Confirm-disable -> destructive, Enable ->
// primary), and the Kill Switch button (component not yet located under this exact name in the
// current tree -- confirm at migration time).
const VARIANT_CLASSES = {
  primary:
    "bg-brand-gradient text-white shadow-glow-brand hover:brightness-110 hover:-translate-y-0.5",
  secondary:
    "bg-panel text-text border border-card-edge hover:bg-bg",
  destructive: "bg-down text-white hover:brightness-110 hover:-translate-y-0.5",
  // Phase 2A: added for the new shadcn Dialog/Sheet/Command primitives' own generated markup
  // (icon-only close buttons, InputGroup's default button treatment) -- transparent, no border,
  // no gradient/shadow, since these are chrome (close a panel) not a primary/secondary CTA.
  ghost: "bg-transparent text-text-faint hover:bg-bg hover:text-text-dim",
  // Same Phase 2A source (DialogFooter's optional secondary "Close" action) -- a bordered variant
  // distinct from `secondary` only in starting fully transparent instead of bg-panel.
  outline: "bg-transparent text-text border border-card-edge hover:bg-bg",
} as const;

export type ButtonVariant = keyof typeof VARIANT_CLASSES;

// Phase 2A: `size` didn't exist before this -- every pre-existing call site renders with the
// same px-4/py-2/text-xs treatment (now `size="default"`, the default), so this is additive.
// `icon-sm` exists only for the new Dialog/Sheet primitives' square icon-only close buttons.
const SIZE_CLASSES = {
  default: "px-4 py-2 text-xs",
  "icon-sm": "size-7 p-0",
} as const;

export type ButtonSize = keyof typeof SIZE_CLASSES;

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    size?: ButtonSize;
  }
>(function Button({ className, variant = "primary", size = "default", ...props }, ref) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-btn font-semibold transition duration-300 ease-out disabled:pointer-events-none disabled:opacity-50",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      {...props}
    />
  );
});
