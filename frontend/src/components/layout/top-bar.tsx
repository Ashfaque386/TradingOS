"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { PERMISSIONS, type PermissionKey } from "@/lib/permissions";
import type { Role } from "@/lib/api";

// REL-011 E11.3: `permission` is only set on links whose page is itself role-restricted
// server-side (today just /audit) -- every other route stays visible to all roles, since the
// roadmap's "cannot see... any mutating control" wording is about controls, not read-only pages.
const NAV_LINKS: { href: string; label: string; permission?: PermissionKey }[] = [
  { href: "/", label: "Portfolio & Risk" },
  { href: "/agents", label: "Agent Console" },
  { href: "/strategies", label: "Strategies" },
  { href: "/paper-trading", label: "Paper Trading" },
  { href: "/chat", label: "Chat" },
  { href: "/audit", label: "Audit", permission: "readAudit" },
  { href: "/settings", label: "Settings" },
];

function visibleLinks(role: Role | undefined) {
  return NAV_LINKS.filter(
    (link) => !link.permission || (!!role && (PERMISSIONS[link.permission] as readonly string[]).includes(role)),
  );
}

export function TopBar({ connected, subtitle }: { connected: boolean; subtitle: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 px-6 py-4 sm:px-8">
      <div className="flex items-center gap-3">
        <div className="relative h-2.5 w-2.5">
          <span
            className={cn(
              "absolute inset-0 rounded-full",
              connected ? "bg-emerald-400" : "bg-amber-400",
            )}
          />
          {connected && (
            <span className="absolute inset-0 animate-ping rounded-full bg-emerald-400 opacity-75" />
          )}
        </div>
        <div>
          <h1 className="text-sm font-semibold tracking-[0.08em] text-zinc-100">
            TRADING<span className="text-cyan-400">OS</span>
          </h1>
          <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">{subtitle}</p>
        </div>
      </div>

      <nav className="flex gap-1 rounded-lg bg-black/30 p-1">
        {visibleLinks(user?.role).map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              pathname === link.href
                ? "bg-white/10 text-zinc-100"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            {link.label}
          </Link>
        ))}
      </nav>

      <div className="flex items-center gap-4">
        <div className="text-right">
          <div className="font-mono-tabular text-sm text-zinc-300">
            {now
              ? now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })
              : "--:--:--"}{" "}
            <span className="text-zinc-600">IST</span>
          </div>
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">
            {connected ? "Live stream connected" : "Reconnecting…"}
          </div>
        </div>

        {user && (
          <div className="flex items-center gap-2 border-l border-white/10 pl-4">
            <div className="text-right">
              <div className="text-xs text-zinc-300">{user.email}</div>
              <div className="text-[10px] uppercase tracking-wider text-cyan-400/80">{user.role}</div>
            </div>
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
        )}
      </div>
    </header>
  );
}
