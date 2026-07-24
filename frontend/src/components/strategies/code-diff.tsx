"use client";

import { diffLines } from "diff";
import { cn } from "@/lib/utils";

export function CodeDiff({ before, after }: { before: string; after: string }) {
  const parts = diffLines(before, after);

  return (
    <pre className="max-h-[420px] overflow-auto rounded-xl border border-white/5 bg-black/40 p-3 font-mono text-[11px] leading-relaxed">
      {parts.map((part, i) => {
        const lines = part.value.replace(/\n$/, "").split("\n");
        return lines.map((line, j) => (
          <div
            key={`${i}-${j}`}
            className={cn(
              "px-2 -mx-2",
              part.added && "bg-emerald-500/10 text-emerald-300",
              part.removed && "bg-rose-500/10 text-rose-300",
              !part.added && !part.removed && "text-zinc-500",
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
