import { useSearchParams } from "react-router-dom";

import type { Period } from "../api/types";

export const PERIODS: { key: Period; label: string }[] = [
  { key: "origine", label: "Origine" },
  { key: "ytd", label: "Début d'année" },
  { key: "1y", label: "1 an" },
  { key: "3y", label: "3 ans" },
  { key: "5y", label: "5 ans" },
];

/** Période partagée entre les pages Performance et Risque, conservée dans l'URL (?periode=). */
export function usePeriod(): [Period, (p: Period) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("periode");
  const period = (PERIODS.some((p) => p.key === raw) ? raw : "origine") as Period;
  return [period, (p) => setParams((prev) => { prev.set("periode", p); return prev; }, { replace: true })];
}

/** Une période plus longue que l'historique est désactivée. */
export default function PeriodSelector({ value, onChange, available }: {
  value: Period;
  onChange: (p: Period) => void;
  available?: Partial<Record<Period, boolean>>;
}) {
  return (
    <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="Période">
      {PERIODS.map((p) => {
        const off = available ? available[p.key] === false : false;
        const on = p.key === value;
        return (
          <button key={p.key} role="radio" aria-checked={on} disabled={off}
                  title={off ? "Historique trop court pour cette période" : undefined}
                  onClick={() => onChange(p.key)}
                  className={`rounded-md border px-2.5 py-1 text-sm ${on ? "border-accent bg-surface-2 text-ink" : "border-line text-ink-2 hover:text-ink"} disabled:cursor-not-allowed disabled:opacity-40`}>
            {p.label}
          </button>
        );
      })}
    </div>
  );
}
