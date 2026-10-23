import { type ReactNode, useState } from "react";

import { ApiError } from "../api/client";
import type { Meta } from "../api/types";
import { date, dateTime } from "../lib/format";

export function Card({ title, children, aside, className = "" }: {
  title?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface p-4 ${className}`}>
      {(title || aside) && (
        <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
          {aside}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, valueClass = "" }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${valueClass}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

/** Date et source des données d'un bloc. Obligatoire sous toute valeur affichée. */
export function Source({ meta }: { meta?: Meta }) {
  if (!meta) return null;
  const names = meta.sources.map((s) => (s.last_date ? `${s.name} (cours au ${date(s.last_date)})` : s.name));
  return (
    <p className="mt-3 text-xs text-muted">
      Valorisation au {date(meta.as_of)}
      {names.length > 0 ? ` · Sources : ${names.join(" ; ")}` : " · Aucune donnée de marché"}
      {" · Calculé le "}
      {dateTime(meta.generated_at)}
    </p>
  );
}

export function Warnings({ items }: { items: string[] }) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const shown = open ? items : items.slice(0, 3);
  return (
    <div className="rounded-md border border-line p-3 text-sm" style={{ background: "var(--warn-bg)" }} role="status">
      <div className="mb-1 font-medium text-warn">Avertissements ({items.length})</div>
      <ul className="list-disc space-y-0.5 pl-5 text-ink-2">
        {shown.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
      {items.length > 3 && (
        <button className="mt-1 text-xs text-accent underline" onClick={() => setOpen(!open)}>
          {open ? "Réduire" : `Voir les ${items.length - 3} autres`}
        </button>
      )}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="rounded-md border border-line p-3 text-sm" role="alert" style={{ background: "var(--warn-bg)" }}>
      <div className="font-medium text-bad">{e ? e.message : String(error)}</div>
      {e && e.errors.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-ink-2">
          {e.errors.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Loading({ label = "Chargement…" }: { label?: string }) {
  return <p className="py-8 text-center text-sm text-muted">{label}</p>;
}

/** Bandeau fixe : visible sur toutes les pages dès qu'une donnée est simulée. */
export function SimulatedBanner() {
  return (
    <div
      className="sticky top-0 z-50 px-4 py-1.5 text-center text-sm font-semibold"
      style={{ background: "var(--sim-bg)", color: "var(--sim-text)" }}
      role="alert"
    >
      Données simulées : cours et transactions fictifs, aucune valeur réelle.
    </div>
  );
}

export function Button({ children, variant = "primary", ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
}) {
  const cls = {
    primary: "bg-accent text-white hover:opacity-90",
    ghost: "border border-line text-ink hover:bg-surface-2",
    danger: "border border-line text-bad hover:bg-surface-2",
  }[variant];
  return (
    <button {...rest} className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${cls} ${rest.className ?? ""}`}>
      {children}
    </button>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-xs text-muted">
      <span>{label}</span>
      {children}
      {hint && <span className="text-[11px]">{hint}</span>}
    </label>
  );
}
