import { cn } from "@/lib/utils";

export function GlassCard({
  className,
  children,
  title,
  eyebrow,
  action,
}: {
  className?: string;
  children: React.ReactNode;
  title?: string;
  eyebrow?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className={cn("glass-panel rounded-2xl p-5", className)}>
      {(title || eyebrow) && (
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            {eyebrow && (
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-500">
                {eyebrow}
              </div>
            )}
            {title && <h2 className="mt-0.5 text-sm font-medium text-zinc-200">{title}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
