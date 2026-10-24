"""
Fournisseur Yahoo Finance (bibliothèque yfinance). Seul fichier qui importe yfinance.

Données gratuites et non garanties : erreurs ponctuelles possibles, pas
d'engagement de disponibilité. Les cotations de Londres en pence (GBp) sont
converties en livres.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta

import pandas as pd

from ..errors import MissingCurrency, ProviderUnavailable, UnknownTicker
from ..splits import Split
from .base import Fundamentals, InstrumentInfo, MarketDataProvider, PriceSeries, clean_series, fundamentals_frame

SOURCE = "Yahoo Finance"

# Correspondance explicite des lignes Yahoo (comptes annuels) vers nos champs. Une ligne
# absente reste absente. Seule la dette est construite (voir `_debt`).
FUNDAMENTAL_ROWS = {
    "cashflow": {"Operating Cash Flow": "ocf", "Capital Expenditure": "capex",
                 "Free Cash Flow": "fcf_reported", "Stock Based Compensation": "sbc"},
    "income_stmt": {"Total Revenue": "revenue", "Interest Expense": "interest_expense",
                    "Pretax Income": "pretax_income", "Tax Provision": "tax_provision",
                    "Diluted Average Shares": "diluted_shares"},
    "balance_sheet": {"Cash Cash Equivalents And Short Term Investments": "cash_sti",
                      "Minority Interest": "minority_interest"},
}


def _yf():
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover - dépendance déclarée
        raise ProviderUnavailable("yahoo", "bibliothèque yfinance absente") from e
    return yf


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    simulated = False

    def _history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        yf = _yf()
        try:
            # auto_adjust=False : la colonne Close est ajustée des divisions,
            # pas des dividendes (voir base.py).
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")   # dépréciations pandas internes à yfinance
                df = yf.Ticker(symbol).history(
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    auto_adjust=False, actions=False, raise_errors=True)
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ("delisted", "no data", "not found", "no timezone", "404")):
                raise UnknownTicker(symbol) from e
            raise ProviderUnavailable("yahoo", str(e)) from e
        return df

    def daily_closes(self, ticker: str, start: date, end: date) -> PriceSeries:
        df = self._history(ticker, start, end)
        if df is None or df.empty or "Close" not in df:
            raise UnknownTicker(ticker)
        s = clean_series(df["Close"])
        if self._raw_currency(ticker) == "GBp":
            s = s / 100.0
        return PriceSeries(ticker, s, SOURCE)

    def fx_rates(self, currency: str, start: date, end: date) -> PriceSeries:
        if currency == "EUR":
            idx = pd.date_range(start, end, freq="D")
            return PriceSeries("EUR", pd.Series(1.0, index=idx), "identité")
        symbol = f"{currency}EUR=X"
        try:
            df = self._history(symbol, start, end)
        except UnknownTicker as e:
            raise MissingCurrency(currency, f"paire {symbol} introuvable") from e
        if df is None or df.empty:
            raise MissingCurrency(currency, f"aucune donnée pour {symbol}")
        return PriceSeries(symbol, clean_series(df["Close"]), SOURCE)

    def _raw_currency(self, ticker: str) -> str | None:
        yf = _yf()
        try:
            return yf.Ticker(ticker).fast_info.get("currency")
        except Exception as e:
            raise ProviderUnavailable("yahoo", str(e)) from e

    def instrument_info(self, ticker: str) -> InstrumentInfo:
        yf = _yf()
        raw = self._raw_currency(ticker)
        if not raw:
            raise UnknownTicker(ticker)
        currency = "GBP" if raw == "GBp" else raw.upper()
        name = exchange = None
        try:
            info = yf.Ticker(ticker).get_info() or {}
            name = info.get("longName") or info.get("shortName")
            exchange = info.get("exchange")
        except Exception:
            pass                       # le nom est facultatif, la devise ne l'est pas
        return InstrumentInfo(ticker, currency, name=name, exchange=exchange)

    def splits(self, ticker: str) -> list[Split]:
        yf = _yf()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = yf.Ticker(ticker).splits
        except Exception as e:
            raise ProviderUnavailable("yahoo", str(e)) from e
        if raw is None or len(raw) == 0:
            return []
        s = clean_series(raw)
        return [Split.from_ratio(ticker, pd.Timestamp(d).date(), float(r)) for d, r in s.items() if r > 0]

    def dividends(self, ticker: str, start: date, end: date) -> PriceSeries:
        yf = _yf()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = yf.Ticker(ticker).dividends
        except Exception as e:
            raise ProviderUnavailable("yahoo", str(e)) from e
        s = clean_series(raw) if raw is not None and len(raw) else pd.Series(dtype=float)
        if len(s) and self._raw_currency(ticker) == "GBp":
            s = s / 100.0
        s = s.loc[pd.Timestamp(start):pd.Timestamp(end)] if len(s) else s
        return PriceSeries(ticker, s, SOURCE)

    def fundamentals(self, ticker: str) -> Fundamentals:
        yf = _yf()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                t = yf.Ticker(ticker)
                info = t.get_info() or {}
                statements = {name: getattr(t, name) for name in FUNDAMENTAL_ROWS}
        except Exception as e:
            raise ProviderUnavailable("yahoo", str(e)) from e
        if not info and all(df is None or df.empty for df in statements.values()):
            raise UnknownTicker(ticker)
        rows: dict[str, pd.Series] = {}
        for name, mapping in FUNDAMENTAL_ROWS.items():
            df = statements[name]
            if df is None or df.empty:
                continue
            for label, f in mapping.items():
                if label in df.index:
                    rows[f] = pd.to_numeric(df.loc[label], errors="coerce")
        bs = statements["balance_sheet"]
        if bs is not None and not bs.empty:
            rows.update(_debt(bs))
        return Fundamentals(ticker, info.get("financialCurrency"), info.get("quoteType"), info.get("sector"),
                            info.get("industry"), fundamentals_frame(rows), SOURCE)


def _debt(bs: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Dette financière et dettes locatives, séparées. La ligne « Total Debt » de Yahoo n'est PAS
    utilisée : selon la société, elle inclut les dettes locatives (LVMH, NVIDIA) ou non (Apple,
    alors même qu'une ligne de locations est publiée). Recoupement documenté dans METHODE.md.
        dette financière = « Long Term Debt » + dette courante,
        dette courante   = « Current Debt », sinon « Current Debt And Capital Lease Obligation »
                           − « Current Capital Lease Obligation » ;
        dettes locatives = « Capital Lease Obligations », sinon long terme + courant.
    Un terme absent rend le total manquant.
    """
    def row(label: str) -> pd.Series:
        return pd.to_numeric(bs.loc[label], errors="coerce") if label in bs.index else \
            pd.Series(float("nan"), index=bs.columns)

    current = row("Current Debt").combine_first(
        row("Current Debt And Capital Lease Obligation") - row("Current Capital Lease Obligation"))
    leases = row("Capital Lease Obligations").combine_first(
        row("Long Term Capital Lease Obligation") + row("Current Capital Lease Obligation"))
    return {"financial_debt": row("Long Term Debt") + current, "lease_liabilities": leases}
