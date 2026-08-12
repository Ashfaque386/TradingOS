import { formatCompactINR } from "@/lib/utils";

/** REL-037: the one place "Total / Used / Available to Trade" is computed and rendered, reused
 * everywhere an account's tradeable capital needs to be shown (dashboard Paper/Live sections,
 * /account, /paper-trading). Total is always Used + Available by construction, matching
 * MarginPanel's own existing arithmetic for the Live side -- callers pass the two real numbers
 * (never a third, independently-computed Total that could silently drift from them). */
export function CapitalSummary({ used, available }: { used: number; available: number }) {
  const total = used + available;
  return (
    <div className="grid grid-cols-3 gap-4">
      <div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
          Total Amount
        </p>
        <p className="font-mono-tabular text-xl font-semibold tracking-tight text-text">
          {formatCompactINR(total)}
        </p>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">Used</p>
        <p className="font-mono-tabular text-xl font-semibold tracking-tight text-text-dim">
          {formatCompactINR(used)}
        </p>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-[0.18em] text-text-faint">
          Available to Trade
        </p>
        <p className="font-mono-tabular text-xl font-semibold tracking-tight text-up">
          {formatCompactINR(available)}
        </p>
      </div>
    </div>
  );
}
