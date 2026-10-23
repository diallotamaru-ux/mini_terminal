// Mise en forme française. Les montants arrivent en chaînes décimales exactes ;
// la conversion en nombre ne sert qu'à l'affichage (2 décimales, bien en deçà
// de la précision d'un double). Une valeur null s'affiche « manquant », jamais 0.

export const MISSING = "manquant";

const nf = (min: number, max: number) =>
  new Intl.NumberFormat("fr-FR", { minimumFractionDigits: min, maximumFractionDigits: max });

const eur2 = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

export function money(v: string | number | null | undefined, currency = "EUR"): string {
  if (v === null || v === undefined || v === "") return MISSING;
  const n = Number(v);
  if (!Number.isFinite(n)) return MISSING;
  if (currency === "EUR") return eur2.format(n);
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency }).format(n);
}

export function signedMoney(v: string | number | null | undefined, currency = "EUR"): string {
  if (v === null || v === undefined) return MISSING;
  const n = Number(v);
  const s = money(Math.abs(n), currency);
  return n > 0 ? `+${s}` : n < 0 ? `−${s}` : s;
}

export function pct(v: string | number | null | undefined, digits = 2, signed = false): string {
  if (v === null || v === undefined) return MISSING;
  const n = Number(v) * 100;
  if (!Number.isFinite(n)) return MISSING;
  const s = `${nf(digits, digits).format(Math.abs(n))} %`;
  if (n < 0) return `−${s}`;
  return signed && n > 0 ? `+${s}` : s;
}

/** Quantité : jusqu'à 8 décimales (crypto), sans zéros inutiles. */
export function qty(v: string | null | undefined): string {
  if (v === null || v === undefined) return MISSING;
  return nf(0, 8).format(Number(v));
}

export function num(v: string | number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return MISSING;
  return nf(0, digits).format(Number(v));
}

export function date(d: string | null | undefined): string {
  if (!d) return MISSING;
  const [y, m, j] = d.slice(0, 10).split("-");
  return `${j}/${m}/${y}`;
}

export function dateTime(d: string | null | undefined): string {
  if (!d) return MISSING;
  return new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

export function signClass(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted";
  const n = Number(v);
  return n > 0 ? "text-good" : n < 0 ? "text-bad" : "text-ink";
}

export const CASH_MODE_LABEL = { avec_especes: "Avec espèces", titres_seuls: "Titres seuls" } as const;
export const TX_LABEL = {
  ACHAT: "Achat",
  VENTE: "Vente",
  DIVIDENDE: "Dividende",
  DEPOT: "Dépôt",
  RETRAIT: "Retrait",
  FRAIS: "Frais",
} as const;
