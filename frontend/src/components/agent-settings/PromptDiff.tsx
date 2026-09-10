"use client";

import { diffLines } from "diff";
import { cn } from "@/lib/utils";

/** FR-101: a line diff between two prompt versions, using the existing `diff` package (same as
 * the legacy prompt-manager). */
export function PromptDiff({ before, after }: { before: string; after: string }) {
  const parts = diffLines(before, after);
  return (
    <pre className="max-h-[420px] overflow-auto rounded-lg border border-card-edge bg-bg p-2 text-[11px] leading-relaxed">
      {parts.map((p, i) => (
        <span
          key={i}
          className={cn(
            p.added && "bg-emerald-500/15 text-emerald-300",
            p.removed && "bg-destructive/15 text-destructive",
            !p.added && !p.removed && "text-text-muted",
          )}
        >
          {p.value
            .split("\n")
            .filter((_, idx, arr) => idx < arr.length - 1 || arr[idx] !== "")
            .map((line, idx) => (
              <span key={idx}>
                {p.added ? "+ " : p.removed ? "- " : "  "}
                {line}
                {"\n"}
              </span>
            ))}
        </span>
      ))}
    </pre>
  );
}
