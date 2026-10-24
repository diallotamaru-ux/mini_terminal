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

const SYMBOL: Record<string, string> = { EUR: "€", USD: "$", GBP: "£", CHF: "CHF", JPY: "¥" };

/** Grand montant des comptes annuels : « 14,21 Md€ », « 807,5 M$ ». null -> « manquant ». */
export function big(v: string | number | null | undefined, currency?: string | null): string {
  if (v === null || v === undefined || v === "") return MISSING;
  const n = Number(v);
  if (!Number.isFinite(n)) return MISSING;
  const a = Math.abs(n);
  const [x, unit] = a >= 1e9 ? [n / 1e9, " Md"] : a >= 1e6 ? [n / 1e6, " M"] : a >= 1e3 ? [n / 1e3, " k"] : [n, " "];
  const digits = Math.abs(x) >= 100 ? 1 : 2;
  const s = nf(digits, digits).format(Math.abs(x));
  const cur = currency ? (SYMBOL[currency] ?? ` ${currency}`) : "";
  return `${x < 0 ? "−" : ""}${s}${unit}${cur}`.replace("  ", " ").trimEnd();
}

/** Nombre décimal sans unité (« 1,20 »), « manquant » si null. */
export function dec(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return MISSING;
  const s = nf(digits, digits).format(Math.abs(v));
  return v < 0 ? `−${s}` : s;
}

/** Déplace la virgule d'une saisie décimale sans passer par un flottant : scaleDecimal("1,15", 9) = "1150000000". */
export function scaleDecimal(input: string, zeros: number): string | null {
  const t = input.trim().replace(/\s/g, "").replace(",", ".");
  const m = /^(-?)(\d*)(?:\.(\d*))?$/.exec(t);
  if (!m || (!m[2] && !m[3])) return null;
  const [, sign, ip, fp = ""] = m;
  const digits = (ip || "0") + fp.padEnd(zeros, "0");
  const cut = (ip || "0").length + zeros;
  const out = `${digits.slice(0, cut)}${digits.length > cut ? "." + digits.slice(cut) : ""}`.replace(/^0+(?=\d)/, "");
  return sign + out;
}
