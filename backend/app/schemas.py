"""
Schémas d'entrée et de sortie de l'API.

Les montants sont des Decimal, sérialisés en chaînes JSON (« 1234.56 ») pour
ne rien perdre en route. Les séries statistiques (historique, rendements)
sont des flottants. Une valeur inconnue vaut null, jamais 0.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from terminal.ledger import CashMode, TxType

AccountKind = Literal["CTO", "PEA", "CRYPTO", "AUTRE"]
AssetClass = Literal["action", "etf", "crypto", "autre"]


def _upper(v: str | None) -> str | None:
    return v.strip().upper() if isinstance(v, str) and v.strip() else None


# ---------------------------------------------------------------------------
# Comptes, cotations, transactions
# ---------------------------------------------------------------------------

class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    broker: str | None = Field(default=None, max_length=80)
    kind: AccountKind
    cash_mode: CashMode
    currency: Literal["EUR"] = "EUR"


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    broker: str | None = Field(default=None, max_length=80)
    kind: AccountKind | None = None
    cash_mode: CashMode | None = None


class AccountOut(AccountIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    n_transactions: int = 0


class ListingIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    isin: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}[A-Za-z0-9]{9}[0-9]$")
    name: str | None = Field(default=None, max_length=200)
    asset_class: AssetClass = "autre"
    exchange: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")

    @field_validator("ticker", "isin", "currency")
    @classmethod
    def _norm(cls, v: str | None) -> str | None:
        return _upper(v)


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    isin: str | None
    name: str | None
    asset_class: str


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ticker: str
    exchange: str | None
    currency: str
    instrument: InstrumentOut


class TransactionIn(BaseModel):
    account_id: int
    date: dt.date
    type: TxType
    ticker: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fees: Decimal = Decimal(0)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    fx_rate: Decimal | None = None
    withholding: Decimal | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("ticker", "currency")
    @classmethod
    def _norm(cls, v: str | None) -> str | None:
        return _upper(v)

    @field_validator("quantity", "price", "amount", "fees", "fx_rate", "withholding")
    @classmethod
    def _finite(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not v.is_finite():
            raise ValueError("valeur non finie")
        return v


class TransactionOut(BaseModel):
    id: int
    account_id: int
    date: dt.date
    type: TxType
    ticker: str | None
    quantity: Decimal | None
    price: Decimal | None
    amount: Decimal | None
    fees: Decimal
    currency: str
    fx_rate: Decimal | None
    withholding: Decimal | None
    note: str | None


# ---------------------------------------------------------------------------
# Portefeuille
# ---------------------------------------------------------------------------

class SourceInfo(BaseModel):
    name: str
    symbols: list[str]
    last_date: dt.date | None
    fetched_at: dt.datetime | None
    simulated: bool


class Meta(BaseModel):
    as_of: dt.date
    generated_at: dt.datetime
    simulated: bool
    provider: str
    sources: list[SourceInfo]
    warnings: list[str]


class PositionOut(BaseModel):
    account_id: int
    account_name: str
    ticker: str
    name: str | None
    isin: str | None
    asset_class: str
    currency: str
    is_open: bool
    quantity: Decimal
    pru: Decimal | None
    pru_eur: Decimal | None
    cost: Decimal
    cost_eur: Decimal | None
    price: Decimal | None
    price_date: dt.date | None
    price_stale: bool
    price_source: str | None
    fx_rate: Decimal | None
    market_value: Decimal | None
    market_value_eur: Decimal | None
    unrealized: Decimal | None
    unrealized_eur: Decimal | None
    unrealized_pct: Decimal | None
    realized: Decimal
    realized_eur: Decimal | None
    dividends: Decimal
    dividends_eur: Decimal | None
    fees: Decimal
    weight: Decimal | None


class SplitOut(BaseModel):
    date: dt.date
    label: str                       # « 10 pour 1 »


class SplitAdjustmentOut(BaseModel):
    """Ajustement appliqué au calcul ; la transaction saisie n'est pas modifiée."""
    tx_id: int | None
    account_id: int
    account_name: str
    ticker: str
    currency: str
    tx_date: dt.date
    tx_type: str
    splits: list[SplitOut]
    factor: str                      # actions nouvelles par action saisie, ex. « 10 » ou « 3/2 »
    quantity_before: Decimal
    quantity_after: Decimal
    price_before: Decimal
    price_after: Decimal


class PositionsOut(BaseModel):
    meta: Meta
    positions: list[PositionOut]
    split_adjustments: list[SplitAdjustmentOut]


class AllocationItem(BaseModel):
    key: str
    label: str
    value_eur: Decimal | None
    weight: Decimal | None


class AccountValue(BaseModel):
    id: int
    name: str
    kind: str
    cash_mode: CashMode
    value_eur: Decimal | None
    securities_eur: Decimal | None
    cash_eur: Decimal | None


class SummaryOut(BaseModel):
    meta: Meta
    complete: bool
    missing: list[str]
    total_value_eur: Decimal | None
    securities_eur: Decimal | None
    cash_eur: Decimal | None
    cost_eur: Decimal | None
    unrealized_eur: Decimal | None
    realized_eur: Decimal | None
    dividends_eur: Decimal | None
    net_contributions_eur: Decimal | None
    accounts: list[AccountValue]
    by_account: list[AllocationItem]
    by_asset: list[AllocationItem]
    by_currency: list[AllocationItem]
    by_class: list[AllocationItem]


class SeriesOut(BaseModel):
    id: int
    name: str
    value: list[float | None]


class HistoryOut(BaseModel):
    meta: Meta
    dates: list[dt.date]
    value: list[float | None]
    net_contributions: list[float | None]
    accounts: list[SeriesOut]


class TwrOut(BaseModel):
    total: float | None
    annualized: float | None
    start: dt.date | None
    end: dt.date | None
    days: int
    warnings: list[str]


class MwrOut(BaseModel):
    rate: float | None
    annualized: bool
    start: dt.date | None
    end: dt.date | None
    days: int
    warnings: list[str]


class PerformanceBlock(BaseModel):
    id: int | None                      # None pour le portefeuille total
    name: str
    cash_mode: CashMode | None
    twr: TwrOut
    twr_securities: TwrOut | None       # poche titres d'un compte avec espèces
    mwr: MwrOut
    gap_points: float | None = None     # TRI - TWR, en points (par an si annualisés, sinon sur la période)
    gap_annualized: bool = False
    gap_comment: str | None = None


class PerformanceOut(BaseModel):
    meta: Meta
    period: str = "origine"
    period_label: str = "Depuis l'origine"
    base_date: dt.date | None = None
    available_periods: dict[str, bool] = {}
    total: PerformanceBlock
    accounts: list[PerformanceBlock]


class AppMeta(BaseModel):
    demo: bool
    provider: str
    simulated: bool
    version: str


class ImportRowError(BaseModel):
    line: int
    message: str


class NewListing(BaseModel):
    ticker: str
    isin: str | None
    currency: str
    name: str | None


class ImportReport(BaseModel):
    dry_run: bool
    committed: bool
    n_rows: int
    n_valid: int
    n_duplicates: int
    errors: list[ImportRowError]
    warnings: list[str]
    new_listings: list[NewListing]
    transactions: list[TransactionIn]


# ---------------------------------------------------------------------------
# Risque et réglages
# ---------------------------------------------------------------------------

Period = Literal["origine", "ytd", "1y", "3y", "5y"]


class RiskFreeOut(BaseModel):
    mode: str
    label: str                              # « EONIA du … au …, puis €STR » : séries de la période affichée
    segments: list[dict]
    source: str
    last_date: dt.date | None
    last_value: float | None                # en %
    simulated: bool


class RiskRowOut(BaseModel):
    name: str
    kind: str
    complete: bool
    first_missing: dt.date | None
    start: dt.date | None
    n_days: int
    n_weeks: int
    total_return: float | None
    annual_return: float | None
    volatility: float | None
    sharpe: float | None
    sharpe_ci: list[float] | None
    sortino: float | None
    max_drawdown: float | None
    calmar: float | None
    var95: float | None
    cvar95: float | None
    beta: float | None
    beta_dimson: float | None
    correlation: float | None
    alpha: float | None
    tracking_error: float | None
    information_ratio: float | None
    information_ratio_ci: list[float] | None
    is_reference: bool
    notes: dict[str, str]


class CurveOut(BaseModel):
    name: str
    values: list[float | None]


class ReferenceOut(BaseModel):
    index: int
    ticker: str
    name: str
    currency: str
    withholding: float


class RiskOut(BaseModel):
    meta: Meta
    period: Period
    period_label: str
    base_date: dt.date
    span_days: int
    available_periods: dict[str, bool]
    reference: ReferenceOut                 # référence de comparaison (bêta, alpha, TE, IR)
    references: list[ReferenceOut]
    risk_free: RiskFreeOut
    rows: list[RiskRowOut]
    dates: list[dt.date]
    base100: list[CurveOut]
    drawdown: list[CurveOut]
    rolling_volatility: list[CurveOut]
    rolling_window: int
    short_history: str | None
    warnings: list[str]


class SettingsOut(BaseModel):
    settings: dict
    warnings: list[str] = []


# ---------------------------------------------------------------------------
# Diversification
# ---------------------------------------------------------------------------

class ContribItem(BaseModel):
    key: str
    label: str
    contribution: float | None        # part (somme 1) : contribution au risque, ou composante du facteur
    weight: float | None = None


class LineOut(BaseModel):
    key: str
    label: str
    ticker: str
    asset_class: str
    weight: float | None
    n_weeks: int
    partial: bool


class ExcludedOut(BaseModel):
    key: str
    label: str
    n_weeks: int
    reason: str


class HighamOut(BaseModel):
    applied: bool
    frobenius_rel: float | None
    max_corr_change: float | None
    threshold: float | None
    warning: bool


class MatrixOut(BaseModel):
    labels: list[str]
    values: list[list[float | None]]


class DiversificationOut(BaseModel):
    meta: Meta
    period: str
    period_label: str
    base_date: dt.date
    available_periods: dict[str, bool]
    window_start: dt.date
    window_end: dt.date
    window_weeks: int
    min_weeks: int
    partial_mode: str
    estimator: str
    estimator_label: str
    shrinkage: float | None
    t_min: int
    t_max: int
    higham: HighamOut
    lines: list[LineOut]
    excluded: list[ExcludedOut]
    cash_share: float | None
    sigma_risky: float | None
    sigma_total: float | None
    correlation: MatrixOut
    contributions: dict[str, list[ContribItem]]
    enb_pca: float | None
    enb_mt: float | None
    n_lines: int
    pc1_variance_share: float | None
    pc1_eigen_share: float | None
    pc1_loadings: list[ContribItem]
    mt_contributions: list[ContribItem]
    text: str
    warnings: list[str]


class SimulationIn(BaseModel):
    period: Period = "origine"
    ticker: str = Field(min_length=1, max_length=20)
    pct: float = Field(ge=0, le=100)          # en %
    mode: Literal["frais", "realloc"] = "frais"


class ScenarioOut(BaseModel):
    enb_pca: float | None
    enb_mt: float | None
    sigma_risky: float | None
    sigma_total: float | None
    max_drawdown: float | None


class SimContrib(BaseModel):
    key: str
    label: str
    weight_before: float | None
    weight_after: float | None
    before: float | None
    after: float | None


class SimulationOut(BaseModel):
    target: str
    target_label: str
    pct: float
    mode: str
    formula: str
    before: ScenarioOut
    after: ScenarioOut
    contributions: list[SimContrib]
    drawdown_start: dt.date | None
    drawdown_end: dt.date | None
    estimator_label: str
    notes: list[str]
    disclaimer: str


# ---------------------------------------------------------------------------
# Valorisation (DCF inversé)
# ---------------------------------------------------------------------------

FundamentalField = Literal["revenue", "ocf", "capex", "fcf_reported", "sbc", "interest_expense", "pretax_income",
                           "tax_provision", "financial_debt", "lease_liabilities", "cash_sti", "lt_investments", "minority_interest",
                           "diluted_shares"]


class FundamentalCell(BaseModel):
    value: Decimal | None                    # None = manquant
    manual: bool = False
    note: str | None = None
    entered_at: dt.datetime | None = None


class FundamentalYear(BaseModel):
    fiscal_end: dt.date
    values: dict[str, FundamentalCell]
    fcff: float | None                       # FCFF de l'exercice selon les hypothèses (None = non calculable)


class MissingOut(BaseModel):
    fiscal_end: dt.date | None
    field: str
    label: str
    remedy: str


class KOut(BaseModel):
    k: float | None
    label: str                               # « commun EUR », « MEDAF », « personnalisé »
    detail: str                              # composantes, sources et dates
    g: float | None = None                   # g implicite avec ce k
    error: str | None = None


class ProfileOut(BaseModel):
    standard: str
    standard_label: str
    standard_proposed: bool                  # valeur par défaut non confirmée
    interest_class: str
    financial: bool | None
    k: float | None
    horizon: int
    g_term: float
    fcf_years: int
    sbc_deduct: bool
    statutory_tax: float | None
    accept_interest_approx: bool
    accept_minority_approx: bool
    custom: list[str]                        # hypothèses différentes des réglages


class EvOut(BaseModel):
    price: float
    price_date: dt.date | None
    price_currency: str
    fx: float
    accounts_currency: str
    shares: float
    market_cap: float
    debt: float
    debt_rule: str
    cash: float
    lt_investments: float | None               # None : manquant, non retranché
    minority: float | None
    ev: float
    balance_date: dt.date


class GrowthOut(BaseModel):
    value: float | None
    status: str                              # ok, non_significatif, manquant
    years: int
    n_points: int
    start: dt.date | None
    end: dt.date | None


class SensiCell(BaseModel):
    k: float
    g_term: float
    g: float | None
    reason: str | None


class PricePoint(BaseModel):
    time: dt.date
    value: float


class ValuationOut(BaseModel):
    meta: Meta
    ticker: str
    name: str
    isin: str | None
    asset_class: str
    status: str                              # ok, exclue, bloquee, impossible
    reason: str | None                       # exclusion, blocage ou impossibilité
    missing: list[MissingOut]
    sector: str | None
    industry: str | None
    fundamentals_source: str | None
    fundamentals_fetched_at: dt.datetime | None
    fundamentals_simulated: bool
    accounts_currency: str | None
    years: list[FundamentalYear]
    profile: ProfileOut | None
    fcff_rule: str | None
    fcff0: float | None
    ev_multiple: float | None                  # VE / FCFF0 observé (contrôle de vraisemblance du g)
    fcf_window: list[dt.date]
    tax_rate: float | None
    tax_source: str | None
    ev: EvOut | None
    k_used: KOut | None
    k_common: KOut | None
    k_capm: KOut | None
    g: float | None
    sentence: str | None
    growth_fcff: GrowthOut | None
    growth_revenue: GrowthOut | None
    sensitivity: list[list[SensiCell]]
    prices: list[PricePoint]
    warnings: list[str]


class ValuationRow(BaseModel):
    ticker: str
    name: str
    status: str
    reason: str | None
    g: float | None
    k: float | None
    k_label: str | None
    growth_fcff: GrowthOut | None
    growth_revenue: GrowthOut | None
    ev_multiple: float | None                # VE / FCFF de départ
    balance_date: dt.date | None
    price_date: dt.date | None
    manual: bool                             # au moins une saisie manuelle
    approximations: bool                     # au moins une approximation acceptée


class ValuationSummaryOut(BaseModel):
    meta: Meta
    horizon: int
    g_term: float
    rows: list[ValuationRow]                 # analysables, triées par g implicite
    others: list[ValuationRow]               # bloquées, impossibles, exclues


class ProfileIn(BaseModel):
    """Hypothèses et attributs comptables d'un titre. null = valeur par défaut."""
    standard: Literal["us_gaap", "ifrs"] | None = None
    interest_class: Literal["exploitation", "financement"] | None = None
    financial: bool | None = None
    k: Decimal | None = Field(default=None, gt=Decimal("-0.5"), le=Decimal("0.5"))
    horizon: int | None = Field(default=None, ge=1, le=30)
    g_term: Decimal | None = Field(default=None, ge=Decimal("-0.05"), le=Decimal("0.06"))
    fcf_years: int | None = Field(default=None, ge=1, le=5)
    sbc_deduct: bool | None = None
    statutory_tax: Decimal | None = Field(default=None, ge=0, le=Decimal("0.6"))
    accept_interest_approx: bool = False
    accept_minority_approx: bool = False


class FundamentalIn(BaseModel):
    fiscal_end: dt.date
    field: FundamentalField
    value: Decimal
    note: str | None = Field(default=None, max_length=300)
