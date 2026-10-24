"""
Cache des cours en base, placé devant n'importe quel MarketDataProvider.

- Une plage déjà téléchargée est relue en base. Les cours passés ne changent
  plus ; ceux du jour sont retéléchargés après `ttl`.
- Si le fournisseur est indisponible et qu'un cache existe, le cache est
  servi, avec une source qui le dit (« cache du ... »). Sans cache, l'erreur
  remonte telle quelle.
- Un changement de fournisseur invalide le cache du symbole.
- Les divisions d'actions sont mises en cache de la même façon, retéléchargées
  après `ttl` (une division peut être annoncée à tout moment).
- Les comptes annuels sont gardés `fundamentals_ttl` (7 jours par défaut) : ils ne
  changent qu'à la publication d'un exercice. Valeurs en Decimal ; absente = manquante.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from terminal.errors import ProviderUnavailable
from terminal.marketdata.base import (FUNDAMENTAL_FIELDS, Fundamentals, InstrumentInfo, MarketDataProvider,
                                      PriceSeries, fundamentals_frame)
from terminal.marketdata.rates import RateProvider
from terminal.splits import Split

from .models import FundamentalCache, FundamentalValue, MarketBar, MarketRange, MarketSplit


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class _SeriesCache:
    """Mécanique commune : plages téléchargées, relecture, repli sur le cache en cas de panne."""

    def __init__(self, inner, sessions: sessionmaker[Session], ttl: timedelta = timedelta(hours=6),
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.inner = inner
        self.sessions = sessions
        self.ttl = ttl
        self.now = now
        self.name = inner.name
        self.simulated = inner.simulated


    def _fresh(self, rng: MarketRange | None, start: date, end: date) -> bool:
        if rng is None or rng.provider != self.inner.name:
            return False
        if rng.start > start or rng.end < end:
            return False
        fetched = _utc(rng.fetched_at)
        # Les clôtures antérieures au jour du téléchargement sont définitives.
        return end < fetched.date() or self.now() - fetched < self.ttl

    def _read(self, s: Session, symbol: str, label: str, start: date, end: date,
              rng: MarketRange, note: str = "") -> PriceSeries:
        rows = s.execute(select(MarketBar.date, MarketBar.value)
                         .where(MarketBar.symbol == symbol, MarketBar.date >= start, MarketBar.date <= end)
                         .order_by(MarketBar.date)).all()
        closes = pd.Series([float(v) for _, v in rows],
                           index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in rows]), dtype=float)
        return PriceSeries(label, closes, rng.source + note, simulated=rng.simulated,
                           fetched_at=_utc(rng.fetched_at))

    def _get(self, symbol: str, label: str, start: date, end: date,
             fetch: Callable[[date, date], PriceSeries]) -> PriceSeries:
        with self.sessions() as s:
            rng = s.get(MarketRange, symbol)
            if self._fresh(rng, start, end):
                return self._read(s, symbol, label, start, end, rng)

            same = rng is not None and rng.provider == self.inner.name
            f_start = min(start, rng.start) if same else start
            f_end = max(end, rng.end) if same else end
            try:
                series = fetch(f_start, f_end)
            except ProviderUnavailable:
                if same:
                    note = f" (cache du {_utc(rng.fetched_at).date().isoformat()}, fournisseur indisponible)"
                    return self._read(s, symbol, label, start, end, rng, note)
                raise

            s.execute(delete(MarketBar).where(MarketBar.symbol == symbol))
            s.add_all(MarketBar(symbol=symbol, date=pd.Timestamp(d).date(), value=Decimal(repr(float(v))))
                      for d, v in series.closes.items())
            if rng is None:
                rng = MarketRange(symbol=symbol)
                s.add(rng)
            rng.start, rng.end = f_start, f_end
            rng.source, rng.provider, rng.simulated = series.source, self.inner.name, series.simulated
            rng.fetched_at = self.now()
            s.commit()
            return self._read(s, symbol, label, start, end, rng)


class CachedProvider(_SeriesCache, MarketDataProvider):
    fundamentals_ttl = timedelta(days=7)

    def daily_closes(self, ticker: str, start: date, end: date) -> PriceSeries:
        return self._get(ticker, ticker, start, end,
                         lambda s, e: self.inner.daily_closes(ticker, s, e))

    def fx_rates(self, currency: str, start: date, end: date) -> PriceSeries:
        if currency == "EUR":
            ones = pd.Series(1.0, index=pd.date_range(start, end, freq="D"))
            return PriceSeries("EUR", ones, "identité", simulated=self.simulated)
        return self._get(f"FX:{currency}", f"{currency}EUR", start, end,
                         lambda s, e: self.inner.fx_rates(currency, s, e))

    def instrument_info(self, ticker: str) -> InstrumentInfo:
        return self.inner.instrument_info(ticker)

    def dividends(self, ticker: str, start: date, end: date) -> PriceSeries:
        return self._get(f"DIV:{ticker}", ticker, start, end,
                         lambda s, e: self.inner.dividends(ticker, s, e))

    def fundamentals(self, ticker: str) -> Fundamentals:
        with self.sessions() as s:
            head = s.get(FundamentalCache, ticker)
            same = head is not None and head.provider == self.inner.name
            if same and self.now() - _utc(head.fetched_at) < self.fundamentals_ttl:
                return self._read_fundamentals(s, head)
            try:
                f = self.inner.fundamentals(ticker)
            except ProviderUnavailable:
                if same:
                    note = f" (cache du {_utc(head.fetched_at).date().isoformat()}, fournisseur indisponible)"
                    return self._read_fundamentals(s, head, note)
                raise
            s.execute(delete(FundamentalValue).where(FundamentalValue.ticker == ticker))
            s.add_all(FundamentalValue(ticker=ticker, fiscal_end=pd.Timestamp(d).date(), field=col,
                                       value=Decimal(repr(float(v))))
                      for d, row in f.table.iterrows() for col, v in row.items() if pd.notna(v))
            if head is None:
                head = FundamentalCache(ticker=ticker)
                s.add(head)
            head.provider, head.source, head.simulated = self.inner.name, f.source, f.simulated
            head.fetched_at = self.now()
            head.currency, head.quote_type, head.sector, head.industry = f.currency, f.quote_type, f.sector, f.industry
            s.commit()
            return self._read_fundamentals(s, head)

    def _read_fundamentals(self, s: Session, head: FundamentalCache, note: str = "") -> Fundamentals:
        rows = s.scalars(select(FundamentalValue).where(FundamentalValue.ticker == head.ticker)).all()
        by_field: dict[str, dict] = {f: {} for f in FUNDAMENTAL_FIELDS}
        for r in rows:
            by_field.setdefault(r.field, {})[pd.Timestamp(r.fiscal_end)] = float(r.value)
        table = fundamentals_frame({f: pd.Series(v, dtype=float) for f, v in by_field.items() if v})
        return Fundamentals(head.ticker, head.currency, head.quote_type, head.sector, head.industry, table,
                            head.source + note, simulated=head.simulated, fetched_at=_utc(head.fetched_at))

    def splits(self, ticker: str) -> list[Split]:
        symbol = f"SPLITS:{ticker}"
        with self.sessions() as s:
            rng = s.get(MarketRange, symbol)
            fresh = (rng is not None and rng.provider == self.inner.name
                     and self.now() - _utc(rng.fetched_at) < self.ttl)
            if not fresh:
                try:
                    found = self.inner.splits(ticker)
                except ProviderUnavailable:
                    if rng is None or rng.provider != self.inner.name:
                        raise
                    found = None                 # fournisseur en panne : cache existant
                if found is not None:
                    s.execute(delete(MarketSplit).where(MarketSplit.ticker == ticker))
                    s.add_all(MarketSplit(ticker=ticker, date=x.date, numerator=x.numerator,
                                          denominator=x.denominator) for x in found)
                    if rng is None:
                        rng = MarketRange(symbol=symbol)
                        s.add(rng)
                    today = self.now().date()
                    rng.start, rng.end = today, today
                    rng.source, rng.provider, rng.simulated = self.inner.name, self.inner.name, self.simulated
                    rng.fetched_at = self.now()
                    s.commit()
            rows = s.scalars(select(MarketSplit).where(MarketSplit.ticker == ticker)
                             .order_by(MarketSplit.date)).all()
            return [Split(r.ticker, r.date, r.numerator, r.denominator) for r in rows]


class CachedRates(_SeriesCache, RateProvider):
    """Même cache, pour les taux au jour le jour (symboles « RATE:ESTR », « RATE:EONIA »)."""

    def overnight(self, series: str, start: date, end: date) -> PriceSeries:
        return self._get(f"RATE:{series.upper()}", series.upper(), start, end,
                         lambda s, e: self.inner.overnight(series, s, e))

    def long_yield(self, currency: str, start: date, end: date) -> PriceSeries:
        return self._get(f"YIELD10:{currency}", f"{currency}10Y", start, end,
                         lambda s, e: self.inner.long_yield(currency, s, e))
