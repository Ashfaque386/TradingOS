"use client";

// Phase 2E: scoped to what's real -- there's no search backend, so this fuzzy-matches the same
// role-filtered page list TopNav already renders (reusing lib/nav-links.ts, not a duplicate list)
// plus a small fixed set of quick actions that already exist as one-click buttons elsewhere in
// the app. "Kill Switch" deliberately navigates to the real slide-to-confirm control on the
// Portfolio page rather than tripping it directly from here -- that gesture is a deliberate
// friction the app already designed in for this exact safety-critical action, and a command
// palette shouldn't bypass it.

import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { LayoutGrid, LogOut, Play, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { usePermission } from "@/lib/usePermission";
import { visibleLinks } from "@/lib/nav-links";
import { useCommandPaletteStore } from "@/lib/command-palette-store";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

export function CommandPalette() {
  const { open, setOpen } = useCommandPaletteStore();
  const { user, logout } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canTriggerResearch = usePermission("triggerResearch");
  const canKillSwitch = usePermission("killSwitch");

  const trigger = useMutation({
    mutationFn: api.triggerResearch,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-runs"] });
      router.push("/agents");
    },
  });

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, setOpen]);

  function go(href: string) {
    router.push(href);
    setOpen(false);
  }

  if (!user) return null;
  const links = visibleLinks(user.role);

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      title="Command Palette"
      description="Jump to a page or run a quick action"
    >
      <CommandInput placeholder="Search pages and actions…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        <CommandGroup heading="Pages">
          {links.map((link) => (
            <CommandItem key={link.href} onSelect={() => go(link.href)}>
              <LayoutGrid className="h-3.5 w-3.5" />
              {link.label}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Quick Actions">
          {canTriggerResearch && (
            <CommandItem
              onSelect={() => {
                trigger.mutate();
                setOpen(false);
              }}
            >
              <Play className="h-3.5 w-3.5" />
              Trigger Research Cycle
            </CommandItem>
          )}
          {canKillSwitch && (
            <CommandItem onSelect={() => go("/")}>
              <ShieldAlert className="h-3.5 w-3.5" />
              Go to Kill Switch
            </CommandItem>
          )}
          <CommandItem
            onSelect={() => {
              logout();
              setOpen(false);
              router.replace("/login");
            }}
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
