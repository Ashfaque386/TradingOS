"use client";

// REL-012 Phase C (2026-08-04): the persistent sidebar/nav replacing TopBar's horizontal pill
// nav (Phase_7_Frontend_Architecture.md §1.1/E12.3) -- tying all 9 authenticated routes into one
// shell, closing the "doesn't feel like one product" gap the 2026-08-01 audit named.
// REL-012 Phase D (2026-08-04): restyled onto the new tokens as part of the first real
// shell-consuming page's restyle (`/settings`) -- doing it here, once, means every remaining
// route inherits the new shell colors the moment its own content gets restyled, rather than
// re-touching this file 8 times. TopBar's brand mark, nav links, and user/logout controls live
// here; PageHeader carries what's left of TopBar (subtitle, connected-status dot, clock).

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { PERMISSIONS, type PermissionKey } from "@/lib/permissions";
import type { Role } from "@/lib/api";

const NAV_LINKS: { href: string; label: string; permission?: PermissionKey }[] = [
  { href: "/", label: "Portfolio & Risk" },
  { href: "/agents", label: "Agent Console" },
  { href: "/strategies", label: "Strategies" },
  { href: "/backtests", label: "Backtests" },
  { href: "/paper-trading", label: "Paper Trading" },
  { href: "/orders", label: "Orders" },
  { href: "/chat", label: "Chat" },
  { href: "/audit", label: "Audit", permission: "readAudit" },
  { href: "/settings", label: "Settings" },
];

function visibleLinks(role: Role | undefined) {
  return NAV_LINKS.filter(
    (link) => !link.permission || (!!role && (PERMISSIONS[link.permission] as readonly string[]).includes(role)),
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-card-edge bg-panel px-3 py-5">
      <div className="mb-6 px-2">
        <h1 className="font-heading text-sm font-bold tracking-[0.04em] text-brand-gradient">
          TRADINGOS
        </h1>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5">
        {visibleLinks(user?.role).map((link) => {
          const active = pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "relative rounded-md px-3 py-2 text-xs font-medium transition-colors",
                active ? "text-text" : "text-text-faint hover:text-text-dim",
              )}
            >
              {active && (
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0.5 left-0 w-0.5 rounded-full bg-brand-gradient"
                />
              )}
              <span className="pl-2">{link.label}</span>
            </Link>
          );
        })}
      </nav>

      {user && (
        <div className="mt-4 border-t border-card-edge px-2 pt-4">
          <div className="text-xs text-text-dim">{user.email}</div>
          <div className="mt-0.5 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-text-faint">
              {user.role}
            </span>
            <button
              onClick={() => {
                logout();
                router.replace("/login");
              }}
              title="Sign out"
              className="rounded-md p-1.5 text-text-faint transition hover:bg-bg hover:text-text-dim"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
