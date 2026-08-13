"use client";

// Phase 1 top-nav migration: replaces components/layout/sidebar.tsx (brand/nav/user-logout) +
// components/layout/page-header.tsx (connection dot/clock/subtitle) with one sticky bar.
//
// Nav renders in full at >= 768px (md) -- covering tablet, Cypress's 1000x660 default, and
// desktop -- so every existing e2e assertion that looks for a nav link directly (no menu-opening
// step first, see rbac_gating.cy.ts/audit_view.cy.ts) keeps working: centering it doesn't hide it
// behind an interaction. Only the mobile-only (< 768px) preset collapses it behind a hamburger.

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { LogOut, Menu, Search, Settings, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { visibleLinks } from "@/lib/nav-links";
import { useShellStatusStore } from "@/lib/shell-status-store";
import { useCommandPaletteStore } from "@/lib/command-palette-store";
import { scaleIn } from "@/lib/motion";
import { IconBadge } from "@/components/ui/icon-badge";
import { NotificationCenter } from "@/components/layout/notification-center";
import { AccountScopeSwitcher } from "@/components/layout/account-scope-switcher";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function CommandPaletteTrigger() {
  const setOpen = useCommandPaletteStore((s) => s.setOpen);
  // Platform detection only after mount -- navigator.userAgent differs between the SSR pass and
  // the client, so reading it during render would produce a hydration mismatch. The setState call
  // is deferred inside a timeout (same pattern as Clock's setInterval above), not called directly
  // in the effect body, matching this file's existing precedent for effect-driven state.
  const [shortcutLabel, setShortcutLabel] = useState("Ctrl K");
  useEffect(() => {
    const id = setTimeout(() => {
      if (/Mac/.test(navigator.userAgent)) setShortcutLabel("⌘K");
    }, 0);
    return () => clearTimeout(id);
  }, []);

  return (
    <button
      onClick={() => setOpen(true)}
      title="Search (⌘K)"
      aria-label="Open command palette"
      className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-text-faint transition hover:bg-bg hover:text-text-dim"
    >
      <Search className="h-4 w-4" />
      <span className="hidden font-mono-tabular text-[10px] sm:inline">{shortcutLabel}</span>
    </button>
  );
}

// Compact bar-chart wordmark icon, gradient-filled with the same brand-gradient tokens the
// TRADINGOS text uses -- an ascending 3-bar glyph rather than a generic lucide icon so the mark
// reads as bespoke, not templated.
function BrandMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" aria-hidden="true">
      <defs>
        <linearGradient id="brand-mark-gradient" x1="0" y1="24" x2="24" y2="0">
          <stop offset="0%" style={{ stopColor: "var(--color-brand-from)" }} />
          <stop offset="50%" style={{ stopColor: "var(--color-brand-via)" }} />
          <stop offset="100%" style={{ stopColor: "var(--color-brand-to)" }} />
        </linearGradient>
      </defs>
      <rect x="2.5" y="13" width="4" height="8.5" rx="1.2" fill="url(#brand-mark-gradient)" />
      <rect x="10" y="7.5" width="4" height="14" rx="1.2" fill="url(#brand-mark-gradient)" />
      <rect x="17.5" y="2.5" width="4" height="19" rx="1.2" fill="url(#brand-mark-gradient)" />
    </svg>
  );
}

function ConnectionStatus() {
  const { subtitle, connected } = useShellStatusStore();

  return (
    <div className="flex min-w-0 items-center gap-2.5">
      <div className="relative h-1.5 w-1.5 shrink-0">
        <span className={cn("absolute inset-0 rounded-full", connected ? "bg-up" : "bg-warn")} />
        {connected && (
          <span className="absolute inset-0 animate-pulse-glow rounded-full bg-up text-up" />
        )}
      </div>
      <p className="truncate text-[10px] uppercase tracking-[0.16em] text-text-faint">
        {subtitle}
      </p>
    </div>
  );
}

function Clock() {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="hidden shrink-0 font-mono-tabular text-[11px] text-text-dim sm:inline">
      {now ? now.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }) : "--:--:--"}{" "}
      <span className="text-text-faint">IST</span>
    </span>
  );
}

function initials(user: { full_name: string | null; email: string }): string {
  if (user.full_name) {
    const parts = user.full_name.trim().split(/\s+/);
    const first = parts[0]?.[0] ?? "";
    const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
    return (first + last).toUpperCase();
  }
  return user.email.slice(0, 2).toUpperCase();
}

function ProfileMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  if (!user) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Account menu"
      >
        <IconBadge size={32} className="text-[11px] font-semibold">
          {initials(user)}
        </IconBadge>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={10} className="w-56">
        <div className="flex flex-col gap-0.5 px-2 py-1.5">
          <span className="text-xs font-medium text-text">{user.full_name ?? user.email}</span>
          <span className="text-[11px] text-text-faint">{user.email}</span>
          <span className="mt-0.5 text-[10px] uppercase tracking-wider text-text-faint">
            {user.role}
          </span>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push("/settings")} className="gap-2 px-2 py-1.5">
          <Settings className="h-3.5 w-3.5" />
          Account &amp; Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onClick={() => {
            logout();
            router.replace("/login");
          }}
          className="gap-2 px-2 py-1.5"
        >
          <LogOut className="h-3.5 w-3.5" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function NavLink({
  href,
  label,
  onClick,
}: {
  href: string;
  label: string;
  onClick?: () => void;
}) {
  const pathname = usePathname();
  const active = pathname === href;
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "relative shrink-0 whitespace-nowrap px-2.5 py-2.5 text-xs font-medium transition-colors lg:px-3",
        active ? "text-text" : "text-text-faint hover:text-text-dim",
      )}
    >
      {label}
      {active && (
        <span
          aria-hidden="true"
          className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-gradient"
        />
      )}
    </Link>
  );
}

/** A hairline vertical rule between icon-cluster groups -- groups related controls (scope
 * switcher / search+alerts / clock+profile) visually without a heavier boxed-section look.
 * Hidden below `sm` alongside the controls it separates so it never strands itself. */
function Divider() {
  return <span aria-hidden="true" className="hidden h-4 w-px shrink-0 bg-card-edge sm:block" />;
}

export function TopNav() {
  const { user } = useAuth();
  const links = visibleLinks(user?.role);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-card-edge bg-panel">
      {/* Row 1: identity + page context (left), global controls (right) -- everything here is
       * either constant (brand) or state, never the long, ever-growing nav link list, so this
       * row's own width budget stays predictable regardless of how many routes exist. */}
      <div className="mx-auto flex w-full max-w-[1440px] items-center justify-between gap-3 px-4 py-2.5 sm:gap-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-2.5 sm:gap-3">
          <button
            onClick={() => setMobileOpen((v) => !v)}
            className="rounded-md p-1.5 text-text-faint transition hover:bg-bg hover:text-text-dim md:hidden"
            aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
          <div className="flex shrink-0 items-center gap-2">
            <BrandMark />
            <h1 className="font-heading text-sm font-bold tracking-[0.04em] text-brand-gradient">
              TRADINGOS
            </h1>
          </div>
          <span aria-hidden="true" className="hidden h-4 w-px shrink-0 bg-card-edge md:block" />
          <ConnectionStatus />
        </div>

        <div className="flex shrink-0 items-center gap-1 sm:gap-1.5">
          <AccountScopeSwitcher className="hidden sm:inline-flex" />
          <Divider />
          <CommandPaletteTrigger />
          <NotificationCenter />
          <Divider />
          <ProfileMenu />
          <Clock />
        </div>
      </div>

      {/* Row 2: the nav strip proper -- its own full-width row so it never competes with row 1's
       * controls for space. Renders in full at >= 768px (md) -- covering tablet, Cypress's
       * 1000x660 default, and desktop -- so every existing e2e assertion that looks for a nav
       * link directly (no menu-opening step first, see rbac_gating.cy.ts/audit_view.cy.ts) keeps
       * working. `overflow-x-auto` is a safety net for an unusually narrow md viewport or a future
       * 11th link, not the expected case -- real Cypress commands auto-scroll a target into view
       * regardless, so it doesn't put those assertions at risk. */}
      <nav className="no-scrollbar hidden items-center justify-center gap-0.5 overflow-x-auto border-t border-card-edge/60 px-2 md:flex lg:px-4">
        <div className="mx-auto flex max-w-[1440px] items-center gap-0.5">
          {links.map((link) => (
            <NavLink key={link.href} href={link.href} label={link.label} />
          ))}
        </div>
      </nav>

      <AnimatePresence>
        {mobileOpen && (
          <motion.nav
            initial="hidden"
            animate="visible"
            exit="hidden"
            variants={scaleIn}
            className="flex flex-col border-t border-card-edge px-4 py-2 md:hidden"
          >
            <div className="flex items-center justify-between border-b border-card-edge py-2">
              <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-text-faint">
                Account scope
              </span>
              <AccountScopeSwitcher />
            </div>
            {links.map((link) => (
              <NavLink
                key={link.href}
                href={link.href}
                label={link.label}
                onClick={() => setMobileOpen(false)}
              />
            ))}
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}
