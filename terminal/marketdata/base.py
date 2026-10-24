"""
Interface des fournisseurs de données de marché.

Le reste de l'application ne connaît que cette interface. Changer de
fournisseur revient à écrire une nouvelle implémentation dans un seul fichier.

Conventions
-----------
- `daily_closes` renvoie des clôtures ajustées des divisions d'actions mais
  PAS des dividendes : les dividendes sont saisis comme transactions, des cours
  ajustés les compteraient deux fois.
- `fx_rates(devise)` renvoie le nombre d'euros pour une unité de `devise`.
- `splits(ticker)` renvoie l'historique complet des divisions, qui sert à
  ajuster les transactions saisies avant chacune (voir terminal/splits.py).
- `dividends(ticker)` renvoie les dividendes bruts par action, datés de leur
  ex-date, dans la devise de cotation et dans l'unité des cours (ajustés des
  divisions). Ils servent à construire les références dividendes réinvestis.
- `fundamentals(ticker)` renvoie les comptes annuels publiés (un exercice par
  ligne), dans la devise des comptes, montants en unités (pas en milliers).
  Une valeur absente est NaN, jamais 0. Les décaissements (capex) sont
  négatifs, comme dans le tableau des flux.
- Index : dates calendaires sans fuseau horaire, triées, sans doublon.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd

from ..splits import Split


@dataclass(frozen=True)
class InstrumentInfo:
    ticker: str
    currency: str
    name: str | None = None
    exchange: str | None = None


@dataclass(frozen=True)
class PriceSeries:
    ticker: str
    closes: pd.Series                 # flottants, index DatetimeIndex
    source: str
    simulated: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def last_date(self) -> date | None:
        s = self.closes.dropna()
        return None if s.empty else pd.Timestamp(s.index[-1]).date()


# Champs des comptes annuels, dans l'ordre d'affichage.
FUNDAMENTAL_FIELDS = (
    "revenue",            # chiffre d'affaires
    "ocf",                # flux de trésorerie d'exploitation
    "capex",              # investissements corporels et incorporels (négatif)
    "fcf_reported",       # flux disponible publié par le fournisseur (OCF + capex)
    "sbc",                # rémunération en actions
    "interest_expense",   # charge d'intérêts
    "pretax_income",      # résultat avant impôt
    "tax_provision",      # impôt sur les résultats
    "financial_debt",     # dette financière (emprunts, obligations, billets de trésorerie), HORS dettes locatives
    "lease_liabilities",  # dettes locatives (contrats de location), à part
    "cash_sti",           # trésorerie et placements à court terme
    "lt_investments",     # placements financiers non courants (titres à plus d'un an, hors mises en équivalence)
    "minority_interest",  # intérêts minoritaires
    "diluted_shares",     # nombre moyen d'actions dilué de l'exercice
)


@dataclass(frozen=True)
class Fundamentals:
    ticker: str
    currency: str | None          # devise des comptes (peut différer de la devise de cotation)
    quote_type: str | None        # EQUITY, ETF, CRYPTOCURRENCY...
    sector: str | None
    industry: str | None
    table: pd.DataFrame           # index : fins d'exercice ; colonnes : FUNDAMENTAL_FIELDS ; NaN = manquant
    source: str
    simulated: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def fundamentals_frame(rows: dict[str, pd.Series]) -> pd.DataFrame:
    """Assemble les séries par champ en un tableau trié par exercice, toutes colonnes présentes."""
    df = pd.DataFrame({f: rows.get(f, pd.Series(dtype=float)) for f in FUNDAMENTAL_FIELDS}, dtype=float)
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    return df.sort_index().dropna(how="all")


def clean_series(s: pd.Series) -> pd.Series:
    """Normalise un index de cours : dates sans fuseau, triées, uniques, NaN retirés."""
    s = s.astype(float)
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.dropna()


class MarketDataProvider(ABC):
    name: str = "abstrait"
    simulated: bool = False

    @abstractmethod
    def daily_closes(self, ticker: str, start: date, end: date) -> PriceSeries:
        """Clôtures quotidiennes de `ticker` sur [start, end]. Lève UnknownTicker ou ProviderUnavailable."""

    @abstractmethod
    def fx_rates(self, currency: str, start: date, end: date) -> PriceSeries:
        """Euros pour une unité de `currency`. Lève MissingCurrency ou ProviderUnavailable."""

    @abstractmethod
    def instrument_info(self, ticker: str) -> InstrumentInfo:
        """Devise et nom de la cotation. Lève UnknownTicker ou ProviderUnavailable."""

    @abstractmethod
    def splits(self, ticker: str) -> list[Split]:
        """Divisions et regroupements de `ticker`, du plus ancien au plus récent. Liste vide s'il n'y en a pas."""

    @abstractmethod
    def dividends(self, ticker: str, start: date, end: date) -> PriceSeries:
        """Dividendes bruts par action sur [start, end], indexés par ex-date. Série vide s'il n'y en a pas."""

    @abstractmethod
    def fundamentals(self, ticker: str) -> Fundamentals:
        """Comptes annuels publiés. Lève UnknownTicker ou ProviderUnavailable."""
