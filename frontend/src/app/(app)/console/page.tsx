"use client";

import { OrganizationOverview } from "@/components/console";
import { usePageStatus } from "@/hooks/usePageStatus";

/** US5 (FR-080): Organization Command Center home. */
export default function ConsoleHome() {
  usePageStatus("Organization Command Center", true);
  return (
    <main className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-4 p-6 sm:p-8">
      <div>
        <h1 className="text-lg font-semibold">Organization Command Center</h1>
        <p className="text-[11px] text-text-faint">
          Live organisation state — every figure is a real backend read, none is hard-coded.
        </p>
      </div>
      <OrganizationOverview />
    </main>
  );
}
