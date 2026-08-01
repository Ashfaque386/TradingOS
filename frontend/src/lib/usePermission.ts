"use client";

import { useAuth } from "@/lib/auth";
import { PERMISSIONS, type PermissionKey } from "@/lib/permissions";

/** Client-side-only check against the PERMISSIONS table -- defense-in-depth, never the real
 * boundary (that's the server-side require_role/Casbin gate each permission's comment cites). */
export function usePermission(key: PermissionKey): boolean {
  const { user } = useAuth();
  return !!user && (PERMISSIONS[key] as readonly string[]).includes(user.role);
}
