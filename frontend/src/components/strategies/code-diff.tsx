"use client";

import { diffLines } from "diff";
import { cn } from "@/lib/utils";

export function CodeDiff({ before, after }: { before: string; after: string }) {
  const parts = diffLines(before, after);

  return (
    <pre className="max-h-[420px] overflow-auto rounded-xl border border-card-edge bg-bg p-3 font-mono text-[11px] leading-relaxed">
      {parts.map((part, i) => {
        const lines = part.value.replace(/\n$/, "").split("\n");
        return lines.map((line, j) => (
          <div
            key={`${i}-${j}`}
            className={cn(
              "px-2 -mx-2",
              part.added && "bg-up/10 text-up",
              part.removed && "bg-down/10 text-down",
              !part.added && !part.removed && "text-text-faint",
            )}
          >
            <span className="mr-2 select-none opacity-50">
              {part.added ? "+" : part.removed ? "-" : " "}
            </span>
            {line || " "}
          </div>
        ));
      })}
    </pre>
  );
}
