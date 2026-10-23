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
from .base import InstrumentInfo, MarketDataProvider, PriceSeries, clean_series

SOURCE = "Yahoo Finance"


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
