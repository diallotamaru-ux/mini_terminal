// Miroir des schémas Pydantic (backend/app/schemas.py).
// Les montants arrivent en chaînes décimales ("1234.56") ; null = inconnu, jamais 0.

export type Dec = string;
export type CashMode = "avec_especes" | "titres_seuls";
export type AccountKind = "CTO" | "PEA" | "CRYPTO" | "AUTRE";
export type AssetClass = "action" | "etf" | "crypto" | "autre";
export type TxType = "ACHAT" | "VENTE" | "DIVIDENDE" | "DEPOT" | "RETRAIT" | "FRAIS";

export interface Account {
  id: number;
  name: string;
  broker: string | null;
  kind: AccountKind;
  cash_mode: CashMode;
  currency: "EUR";
  n_transactions: number;
}

export interface Listing {
  id: number;
  ticker: string;
  exchange: string | null;
  currency: string;
  instrument: { id: number; isin: string | null; name: string | null; asset_class: AssetClass };
}

export interface TransactionIn {
  account_id: number;
  date: string;
  type: TxType;
  ticker?: string | null;
  quantity?: Dec | null;
  price?: Dec | null;
  amount?: Dec | null;
  fees?: Dec;
  currency?: string | null;
  fx_rate?: Dec | null;
  withholding?: Dec | null;
  note?: string | null;
}

export interface Transaction extends Required<Omit<TransactionIn, "fees">> {
  id: number;
  fees: Dec;
  currency: string;
}

export interface SourceInfo {
  name: string;
  symbols: string[];
  last_date: string | null;
  fetched_at: string | null;
  simulated: boolean;
}

export interface Meta {
  as_of: string;
  generated_at: string;
  simulated: boolean;
  provider: string;
  sources: SourceInfo[];
  warnings: string[];
}

export interface Position {
  account_id: number;
  account_name: string;
  ticker: string;
  name: string | null;
  isin: string | null;
  asset_class: string;
  currency: string;
  is_open: boolean;
  quantity: Dec;
  pru: Dec | null;
  pru_eur: Dec | null;
  cost: Dec;
  cost_eur: Dec | null;
  price: Dec | null;
  price_date: string | null;
  price_stale: boolean;
  price_source: string | null;
  fx_rate: Dec | null;
  market_value: Dec | null;
  market_value_eur: Dec | null;
  unrealized: Dec | null;
  unrealized_eur: Dec | null;
  unrealized_pct: Dec | null;
  realized: Dec;
  realized_eur: Dec | null;
  dividends: Dec;
  dividends_eur: Dec | null;
  fees: Dec;
  weight: Dec | null;
}

export interface AllocationItem {
  key: string;
  label: string;
  value_eur: Dec | null;
  weight: Dec | null;
}

export interface AccountValue {
  id: number;
  name: string;
  kind: string;
  cash_mode: CashMode;
  value_eur: Dec | null;
  securities_eur: Dec | null;
  cash_eur: Dec | null;
}

export interface Summary {
  meta: Meta;
  complete: boolean;
  missing: string[];
  total_value_eur: Dec | null;
  securities_eur: Dec | null;
  cash_eur: Dec | null;
  cost_eur: Dec | null;
  unrealized_eur: Dec | null;
  realized_eur: Dec | null;
  dividends_eur: Dec | null;
  net_contributions_eur: Dec | null;
  accounts: AccountValue[];
  by_account: AllocationItem[];
  by_asset: AllocationItem[];
  by_currency: AllocationItem[];
  by_class: AllocationItem[];
}

export interface History {
  meta: Meta;
  dates: string[];
  value: (number | null)[];
  net_contributions: (number | null)[];
  accounts: { id: number; name: string; value: (number | null)[] }[];
}

export interface Twr {
  total: number | null;
  annualized: number | null;
  start: string | null;
  end: string | null;
  days: number;
  warnings: string[];
}

export interface Mwr {
  rate: number | null;
  annualized: boolean;
  start: string | null;
  end: string | null;
  days: number;
  warnings: string[];
}

export interface PerformanceBlock {
  id: number | null;
  name: string;
  cash_mode: CashMode | null;
  twr: Twr;
  twr_securities: Twr | null;
  mwr: Mwr;
}

export interface Performance {
  meta: Meta;
  total: PerformanceBlock;
  accounts: PerformanceBlock[];
}

export interface AppMeta {
  demo: boolean;
  provider: string;
  simulated: boolean;
  version: string;
}

export interface ImportReport {
  dry_run: boolean;
  committed: boolean;
  n_rows: number;
  n_valid: number;
  n_duplicates: number;
  errors: { line: number; message: string }[];
  warnings: string[];
  new_listings: { ticker: string; isin: string | null; currency: string; name: string | null }[];
  transactions: TransactionIn[];
}
