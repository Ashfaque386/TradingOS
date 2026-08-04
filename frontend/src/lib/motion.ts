import type { Transition, Variants } from "framer-motion";

// REL-012 E12.7 (2026-08-04): the standard animation vocabulary, Phase 7 §1.3 -- one shared set
// so motion feels consistent rather than ad-hoc per component. Every preset lands inside the
// spec'd 0.4s-0.7s range. Explicit rule from the same section: exactly one entrance animation per
// element, and re-renders of already-visible data must never re-trigger it -- these are plain
// `initial`/`animate` variants (not `whileInView`/keyed remounts), so a parent that stays mounted
// across a data refresh only plays the entrance once, on first mount.

export const ENTRANCE_TRANSITION: Transition = { duration: 0.5, ease: "easeOut" };

/** Default page/section/card entrance. */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: ENTRANCE_TRANSITION },
};

/** Modals, dropdowns, confirm dialogs (e.g. the Kill Switch re-arm confirmation). */
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.4, ease: "easeOut" } },
};

/** Toasts, bottom sheets, inline reveal forms (reject-reason, stage-change, add-channel). */
export const slideUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" } },
  exit: { opacity: 0, y: 8, transition: { duration: 0.2, ease: "easeIn" } },
};

/** Wrap a grid/list container in this, each child in `staggerItem`, for a small per-item delay
 * instead of all items animating in at once. */
export const staggerContainer: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.05 } },
};

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut" } },
};

/** Very slow, subtle float for hero/empty-state icon containers only -- never on data-bearing
 * elements, where motion on the number itself would be distracting. */
export const floatingIcon: Transition = {
  duration: 7,
  repeat: Infinity,
  repeatType: "mirror",
  ease: "easeInOut",
};
