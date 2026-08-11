// Extracted from the retired components/layout/sidebar.tsx (Phase 1 top-nav migration) so both
// TopNav's desktop row and its mobile dropdown import the exact same filter logic -- role-based
// visibility behaves identically regardless of which visual bucket a link renders in.

import { PERMISSIONS, type PermissionKey } from "@/lib/permissions";
import type { Role } from "@/lib/api";

export const NAV_LINKS: { href: string; label: string; permission?: PermissionKey }[] = [
  { href: "/", label: "Portfolio & Risk" },
  { href: "/agents", label: "Agent Console" },
  { href: "/strategies", label: "Strategies" },
  { href: "/backtests", label: "Backtests" },
  { href: "/account", label: "Account" },
  { href: "/paper-trading", label: "Paper Trading" },
  { href: "/orders", label: "Orders" },
  { href: "/chat", label: "Chat" },
  { href: "/audit", label: "Audit", permission: "readAudit" },
  { href: "/settings", label: "Settings" },
];

export function visibleLinks(role: Role | undefined) {
  return NAV_LINKS.filter(
    (link) => !link.permission || (!!role && (PERMISSIONS[link.permission] as readonly string[]).includes(role)),
  );
}
