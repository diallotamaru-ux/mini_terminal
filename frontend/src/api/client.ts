import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  Account,
  AppMeta,
  History,
  ImportReport,
  Listing,
  AnalysisSettings,
  Diversification,
  FundamentalField,
  ProfileIn,
  Valuation,
  ValuationSummary,
  Performance,
  Period,
  Risk,
  Simulation,
  Position,
  Meta,
  SplitAdjustment,
  Summary,
  Transaction,
  TransactionIn,
} from "./types";

/** Erreur d'API : message lisible et, pour une validation, la liste détaillée. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public errors: string[] = [],
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "Serveur injoignable. L'API est-elle lancée ?");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? formatPydantic(detail) : `Erreur ${res.status}`;
    throw new ApiError(res.status, msg, body?.errors ?? []);
  }
  return body as T;
}

function formatPydantic(detail: { loc?: (string | number)[]; msg?: string }[]): string {
  return detail.map((d) => `${(d.loc ?? []).slice(1).join(".") || "requête"} : ${d.msg}`).join(" ; ");
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const api = {
  meta: () => request<AppMeta>("/api/meta"),
  accounts: () => request<Account[]>("/api/accounts"),
  createAccount: (b: Omit<Account, "id" | "n_transactions" | "currency">) => request<Account>("/api/accounts", json("POST", b)),
  updateAccount: (id: number, b: Partial<Account>) => request<Account>(`/api/accounts/${id}`, json("PATCH", b)),
  deleteAccount: (id: number) => request<void>(`/api/accounts/${id}`, { method: "DELETE" }),
  listings: () => request<Listing[]>("/api/listings"),
  createListing: (b: { ticker: string; isin?: string | null; asset_class: string; currency?: string | null }) =>
    request<Listing>("/api/listings", json("POST", b)),
  transactions: () => request<Transaction[]>("/api/transactions"),
  createTransaction: (b: TransactionIn) => request<Transaction>("/api/transactions", json("POST", b)),
  deleteTransaction: (id: number) => request<void>(`/api/transactions/${id}`, { method: "DELETE" }),
  importCsv: (file: File, dryRun: boolean) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<ImportReport>(`/api/imports/csv?dry_run=${dryRun}`, { method: "POST", body: fd });
  },
  summary: () => request<Summary>("/api/portfolio/summary"),
  positions: () =>
    request<{ meta: Meta; positions: Position[]; split_adjustments: SplitAdjustment[] }>("/api/portfolio/positions"),
  history: () => request<History>("/api/portfolio/history"),
  performance: (period: Period) => request<Performance>(`/api/portfolio/performance?period=${period}`),
  risk: (period: Period, reference: number) => request<Risk>(`/api/risk?period=${period}&reference=${reference}`),
  diversification: (period: Period, partial: string) =>
    request<Diversification>(`/api/diversification?period=${period}&partial=${partial}`),
  simulate: (b: { period: Period; ticker: string; pct: number; mode: string }) =>
    request<Simulation>("/api/diversification/simulate", json("POST", b)),
  valuationSummary: () => request<ValuationSummary>("/api/valuation"),
  valuation: (ticker: string) => request<Valuation>(`/api/valuation/${encodeURIComponent(ticker)}`),
  saveProfile: (ticker: string, b: ProfileIn) =>
    request<Valuation>(`/api/valuation/${encodeURIComponent(ticker)}/profile`, json("PUT", b)),
  saveFundamental: (ticker: string, b: { fiscal_end: string; field: FundamentalField; value: string; note: string | null }) =>
    request<Valuation>(`/api/valuation/${encodeURIComponent(ticker)}/fundamentals`, json("PUT", b)),
  deleteFundamental: (ticker: string, fiscalEnd: string, field: string) =>
    request<Valuation>(`/api/valuation/${encodeURIComponent(ticker)}/fundamentals/${fiscalEnd}/${field}`, { method: "DELETE" }),
  settings: () => request<{ settings: AnalysisSettings; warnings: string[] }>("/api/settings"),
  saveSettings: (s: AnalysisSettings) =>
    request<{ settings: AnalysisSettings; warnings: string[] }>("/api/settings", json("PUT", s)),
};

// --- Hooks React Query -------------------------------------------------------

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
export const useAccounts = () => useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
export const useListings = () => useQuery({ queryKey: ["listings"], queryFn: api.listings });
export const useTransactions = () => useQuery({ queryKey: ["transactions"], queryFn: api.transactions });
export const useSummary = () => useQuery({ queryKey: ["portfolio", "summary"], queryFn: api.summary });
export const usePositions = () => useQuery({ queryKey: ["portfolio", "positions"], queryFn: api.positions });
export const useHistory = () => useQuery({ queryKey: ["portfolio", "history"], queryFn: api.history });
export const usePerformance = (period: Period) =>
  useQuery({ queryKey: ["portfolio", "performance", period], queryFn: () => api.performance(period), placeholderData: keepPreviousData });
export const useRisk = (period: Period, reference: number) =>
  useQuery({ queryKey: ["portfolio", "risk", period, reference], queryFn: () => api.risk(period, reference), placeholderData: keepPreviousData });
export const useDiversification = (period: Period, partial: string) =>
  useQuery({ queryKey: ["portfolio", "diversification", period, partial], queryFn: () => api.diversification(period, partial),
    placeholderData: keepPreviousData, retry: false });
export const useValuationSummary = () =>
  useQuery({ queryKey: ["portfolio", "valuation"], queryFn: api.valuationSummary, retry: false });
export const useValuation = (ticker: string) =>
  useQuery({ queryKey: ["portfolio", "valuation", ticker], queryFn: () => api.valuation(ticker), retry: false });

/** Écriture sur une fiche (hypothèses, saisie manuelle) : la réponse est la fiche à jour. */
export function useValuationMutation<A>(ticker: string, fn: (a: A) => Promise<Valuation>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (v) => {
      qc.setQueryData(["portfolio", "valuation", ticker], v);
      qc.invalidateQueries({ queryKey: ["portfolio", "valuation"], exact: true });
    },
  });
}
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: api.settings });

/** Mutation qui invalide tout ce qui dépend du grand livre. */
export function useLedgerMutation<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const k of ["accounts", "listings", "transactions", "portfolio", "settings"]) qc.invalidateQueries({ queryKey: [k] });
    },
  });
}
