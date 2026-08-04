import { cn } from "@/lib/utils";

// REL-012 Phase B (2026-08-04): the new card primitive per Phase_7_Frontend_Architecture.md
// §1.1 -- `24px` radius, `28px`/`16px` (dense) padding, the fixed shadow/border/hover-lift/glow
// rules. New file, not a rewrite of `glass-card.tsx` -- GlassCard stays as-is until Phase D
// migrates each page over one route at a time; nothing in the live app renders through this
// component yet. `interactive` gates the hover-lift + glow per 1.1's own rule ("reserved for
// genuinely interactive cards... not static display panels").
export function Card({
  className,
  children,
  title,
  eyebrow,
  action,
  density = "default",
  interactive = false,
}: {
  className?: string;
  children: React.ReactNode;
  title?: string;
  eyebrow?: string;
  action?: React.ReactNode;
  density?: "default" | "dense";
  interactive?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-card border border-card-edge bg-panel shadow-card",
        density === "default" ? "p-7" : "p-4",
        interactive &&
          "transition duration-300 ease-out hover:-translate-y-1.5 hover:shadow-glow-brand",
        className,
      )}
    >
      {(title || eyebrow) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            {eyebrow && (
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-text-faint">
                {eyebrow}
              </div>
            )}
            {title && (
              <h2 className="mt-0.5 font-heading text-sm font-semibold text-text">{title}</h2>
            )}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
