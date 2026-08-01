"use client";

import type { PermissionKey } from "@/lib/permissions";
import { usePermission } from "@/lib/usePermission";

/** Renders `children` only if the current user holds one of `permission`'s eligible roles,
 * otherwise renders `fallback` (default: nothing). For controls that should be fully invisible
 * to an ineligible role (roadmap exit criterion: a ReadOnlyAuditor "cannot see... any mutating
 * control") -- as opposed to the Kill Switch's own deliberately-kept visible-but-disabled
 * pattern (see kill-switch-button.tsx's own comment for why that one stays as-is). */
export function Gated({
  permission,
  fallback = null,
  children,
}: {
  permission: PermissionKey;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}) {
  const allowed = usePermission(permission);
  return allowed ? <>{children}</> : <>{fallback}</>;
}
