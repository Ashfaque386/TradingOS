import { cn } from "@/lib/utils";

// REL-012 Phase B (2026-08-04): the icon-in-a-glowing-circle wrapper from the reference
// screenshots (Phase_7_Frontend_Architecture.md §1.1) -- a circular panel-colored container with
// a soft brand-gradient glow blurred behind it. Used everywhere the reference screenshots show
// it: stat cards, empty states, nav. Renders any icon element as `children` (this codebase
// already uses lucide-react elsewhere, e.g. hitl-panel.tsx's Check/RotateCcw/X) rather than
// taking an icon-name prop, so it stays icon-library-agnostic.
export function IconBadge({
  children,
  size = 40,
  className,
}: {
  children: React.ReactNode;
  size?: number;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center rounded-full bg-panel text-text",
        className,
      )}
      style={{ width: size, height: size }}
    >
      <span
        aria-hidden="true"
        className="absolute inset-0 -z-10 rounded-full bg-brand-gradient opacity-25 blur-md"
      />
      {children}
    </span>
  );
}
