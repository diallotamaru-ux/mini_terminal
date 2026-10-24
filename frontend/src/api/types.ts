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

export interface SplitAdjustment {
  tx_id: number | null;
  account_id: number;
  account_name: string;
  ticker: string;
  currency: string;
  tx_date: string;
  tx_type: string;
  splits: { date: string; label: string }[];
  factor: string;
  quantity_before: Dec;
  quantity_after: Dec;
  price_before: Dec;
  price_after: Dec;
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
  gap_points: number | null;
  gap_annualized: boolean;
  gap_comment: string | null;
}

export interface Performance {
  meta: Meta;
  period: Period;
  period_label: string;
  base_date: string | null;
  available_periods: Partial<Record<Period, boolean>>;
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

// --- Phase 2 : risque, périodes, réglages -----------------------------------

export type Period = "origine" | "ytd" | "1y" | "3y" | "5y";

export interface RiskRow {
  name: string;
  kind: "portefeuille" | "compte" | "reference";
  complete: boolean;
  first_missing: string | null;
  start: string | null;
  n_days: number;
  n_weeks: number;
  total_return: number | null;
  annual_return: number | null;
  volatility: number | null;
  sharpe: number | null;
  sharpe_ci: [number, number] | null;
  sortino: number | null;
  max_drawdown: number | null;
  calmar: number | null;
  var95: number | null;
  cvar95: number | null;
  beta: number | null;
  beta_dimson: number | null;
  correlation: number | null;
  alpha: number | null;
  tracking_error: number | null;
  information_ratio: number | null;
  information_ratio_ci: [number, number] | null;
  is_reference: boolean;
  notes: Record<string, string>;
}

export interface Curve {
  name: string;
  values: (number | null)[];
}

export interface ReferenceInfo {
  index: number;
  ticker: string;
  name: string;
  currency: string;
  withholding: number;
}

export interface Risk {
  meta: Meta;
  period: Period;
  period_label: string;
  base_date: string;
  span_days: number;
  available_periods: Record<Period, boolean>;
  reference: ReferenceInfo;
  references: ReferenceInfo[];
  risk_free: {
    mode: string;
    label: string;
    segments: { name: string; start: string; end: string }[];
    source: string;
    last_date: string | null;
    last_value: number | null;
    simulated: boolean;
  };
  rows: RiskRow[];
  dates: string[];
  base100: Curve[];
  drawdown: Curve[];
  rolling_volatility: Curve[];
  rolling_window: number;
  short_history: string | null;
  warnings: string[];
}

export interface ReferenceSetting {
  ticker: string;
  name: string;
  currency: string;
  withholding: string;
}

export interface AnalysisSettings {
  reference_1: ReferenceSetting;
  reference_2: ReferenceSetting;
  rf_mode: "estr" | "fixe" | "zero";
  rf_fixed_rate: string | null;
  rolling_window: number;
  covariance: "lw_cc" | "lw_id" | "empirique";
}

// --- Phase 3 : diversification -------------------------------------------------

export interface ContribItem {
  key: string;
  label: string;
  contribution: number | null;
  weight: number | null;
}

export interface Diversification {
  meta: Meta;
  period: Period;
  period_label: string;
  base_date: string;
  available_periods: Record<Period, boolean>;
  window_start: string;
  window_end: string;
  window_weeks: number;
  min_weeks: number;
  partial_mode: "inclure" | "exclure";
  estimator: "lw_cc" | "lw_id" | "empirique";
  estimator_label: string;
  shrinkage: number | null;
  t_min: number;
  t_max: number;
  higham: { applied: boolean; frobenius_rel: number | null; max_corr_change: number | null; threshold: number | null; warning: boolean };
  lines: { key: string; label: string; ticker: string; asset_class: string; weight: number | null; n_weeks: number; partial: boolean }[];
  excluded: { key: string; label: string; n_weeks: number; reason: string }[];
  cash_share: number | null;
  sigma_risky: number | null;
  sigma_total: number | null;
  correlation: { labels: string[]; values: (number | null)[][] };
  contributions: Record<"ligne" | "compte" | "classe", ContribItem[]>;
  enb_pca: number | null;
  enb_mt: number | null;
  n_lines: number;
  pc1_variance_share: number | null;
  pc1_eigen_share: number | null;
  pc1_loadings: ContribItem[];
  mt_contributions: ContribItem[];
  text: string;
  warnings: string[];
}

export interface Scenario {
  enb_pca: number | null;
  enb_mt: number | null;
  sigma_risky: number | null;
  sigma_total: number | null;
  max_drawdown: number | null;
}

export interface Simulation {
  target: string;
  target_label: string;
  pct: number;
  mode: "frais" | "realloc";
  formula: string;
  before: Scenario;
  after: Scenario;
  contributions: { key: string; label: string; weight_before: number | null; weight_after: number | null; before: number | null; after: number | null }[];
  drawdown_start: string | null;
  drawdown_end: string | null;
  estimator_label: string;
  notes: string[];
  disclaimer: string;
}
