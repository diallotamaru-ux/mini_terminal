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


class PerformanceOut(BaseModel):
    meta: Meta
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
