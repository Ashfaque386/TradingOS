import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { floatingIcon } from "@/lib/motion";

// REL-012 Phase B (2026-08-04): the icon-in-a-glowing-circle wrapper from the reference
// screenshots (Phase_7_Frontend_Architecture.md §1.1) -- a circular panel-colored container with
// a soft brand-gradient glow blurred behind it. Used everywhere the reference screenshots show
// it: stat cards, empty states, nav. Renders any icon element as `children` (this codebase
// already uses lucide-react elsewhere, e.g. hitl-panel.tsx's Check/RotateCcw/X) rather than
// taking an icon-name prop, so it stays icon-library-agnostic.
// REL-012 E12.7 (2026-08-04): `floating` opts into §1.3's "Floating icons" vocabulary -- a very
// slow, subtle y oscillation. Off by default: the spec is explicit this belongs on hero/
// empty-state icon containers only, never a data-bearing element, so call sites must opt in
// rather than getting it for free just by using IconBadge (e.g. a stat-card icon shouldn't float).
export function IconBadge({
  children,
  size = 40,
  className,
  floating = false,
}: {
  children: React.ReactNode;
  size?: number;
  className?: string;
  floating?: boolean;
}) {
  return (
    <motion.span
      animate={floating ? { y: [0, -6, 0] } : undefined}
      transition={floating ? floatingIcon : undefined}
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
    </motion.span>
  );
}
