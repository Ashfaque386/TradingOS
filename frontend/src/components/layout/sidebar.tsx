"use client";

// REL-012 Phase C (2026-08-04): the persistent sidebar/nav replacing TopBar's horizontal pill
// nav (Phase_7_Frontend_Architecture.md §1.1/E12.3) -- tying all 9 authenticated routes into one
// shell, closing the "doesn't feel like one product" gap the 2026-08-01 audit named. Deliberately
// keeps the current dark, unrestyled palette everywhere except the active-route indicator (the
// one thing this epic's own spec calls out by name: "uses the brand gradient"). A full re-theme
// of the sidebar itself is Phase D's job, done together with each page's own restyle -- doing it
// here would mean re-touching this file twice. TopBar's brand mark, nav links, and user/logout
// controls move here; TopBar itself is retired by this pass (see PageHeader for what's left of
// it: subtitle, connected-status dot, clock).

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
    <aside className="flex w-56 shrink-0 flex-col border-r border-white/5 px-3 py-5">
      <div className="mb-6 px-2">
        <h1 className="text-sm font-semibold tracking-[0.08em] text-zinc-100">
          TRADING<span className="text-cyan-400">OS</span>
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
                active ? "text-zinc-100" : "text-zinc-500 hover:text-zinc-300",
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
        <div className="mt-4 border-t border-white/5 px-2 pt-4">
          <div className="text-xs text-zinc-300">{user.email}</div>
          <div className="mt-0.5 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wider text-cyan-400/80">
              {user.role}
            </span>
            <button
              onClick={() => {
                logout();
                router.replace("/login");
              }}
              title="Sign out"
              className="rounded-md p-1.5 text-zinc-500 transition hover:bg-white/5 hover:text-zinc-300"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
