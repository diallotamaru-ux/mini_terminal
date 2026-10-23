import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  Account,
  AppMeta,
  History,
  ImportReport,
  Listing,
  Performance,
  Position,
  Meta,
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
  positions: () => request<{ meta: Meta; positions: Position[] }>("/api/portfolio/positions"),
  history: () => request<History>("/api/portfolio/history"),
  performance: () => request<Performance>("/api/portfolio/performance"),
};

// --- Hooks React Query -------------------------------------------------------

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
export const useAccounts = () => useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
export const useListings = () => useQuery({ queryKey: ["listings"], queryFn: api.listings });
export const useTransactions = () => useQuery({ queryKey: ["transactions"], queryFn: api.transactions });
export const useSummary = () => useQuery({ queryKey: ["portfolio", "summary"], queryFn: api.summary });
export const usePositions = () => useQuery({ queryKey: ["portfolio", "positions"], queryFn: api.positions });
export const useHistory = () => useQuery({ queryKey: ["portfolio", "history"], queryFn: api.history });
export const usePerformance = () => useQuery({ queryKey: ["portfolio", "performance"], queryFn: api.performance });

/** Mutation qui invalide tout ce qui dépend du grand livre. */
export function useLedgerMutation<A, R>(fn: (a: A) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const k of ["accounts", "listings", "transactions", "portfolio"]) qc.invalidateQueries({ queryKey: [k] });
    },
  });
}
