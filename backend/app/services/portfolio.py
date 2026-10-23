"""
De la base au cœur de calcul, et retour.

`snapshot()` charge les transactions, récupère cours et taux, et appelle
`terminal` : validation, positions, espèces, valorisation quotidienne. Les
routes ne font que mettre en forme. Une erreur de données de marché sur un
ticker n'arrête pas le calcul : la ligne est valorisée « manquante » et un
avertissement l'explique.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from terminal import ledger, performance
from terminal.errors import MissingCurrency, ProviderUnavailable, UnknownTicker
from terminal.marketdata.base import MarketDataProvider, PriceSeries
from terminal.positions import Position, cash_balances, compute_positions, transaction_rate
from terminal.valuation import MAX_STALE_DAYS, History, build_history

from .. import models, schemas

TX_PRICE_SOURCE = "Prix de la dernière transaction"
LOOKBACK_DAYS = 10            # cours demandés avant la première transaction
STALE_AFTER_DAYS = 4          # au-delà, un cours est signalé ancien (week-end + un férié)
CENT = Decimal("0.01")


def to_decimal(x: float | None, places: int = 6) -> Decimal | None:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return Decimal(repr(round(float(x), places)))


def to_core_tx(t: models.Transaction) -> ledger.Transaction:
    return ledger.Transaction(
        account_id=t.account_id, date=t.date, type=ledger.TxType(t.type), currency=t.currency,
        ticker=t.listing.ticker if t.listing else None, quantity=t.quantity, price=t.price,
        amount=t.amount, fees=t.fees, fx_rate=t.fx_rate, withholding=t.withholding, id=t.id)


def to_core_account(a: models.Account) -> ledger.Account:
    return ledger.Account(a.id, a.name, ledger.CashMode(a.cash_mode), a.currency)


def load_ledger(s: Session) -> tuple[list[models.Account], list[ledger.Account], list[ledger.Transaction],
                                     dict[str, models.Listing]]:
    accounts = list(s.scalars(select(models.Account).order_by(models.Account.id)))
    txs = list(s.scalars(select(models.Transaction)).unique())
    listings = {l.ticker: l for l in s.scalars(select(models.Listing)).unique()}
    return accounts, [to_core_account(a) for a in accounts], [to_core_tx(t) for t in txs], listings


@dataclass(frozen=True)
class AccountInfo:
    """Copie détachée d'un compte : l'instantané est partagé entre requêtes, sans session."""
    id: int
    name: str
    kind: str
    cash_mode: str
    currency: str


@dataclass(frozen=True)
class ListingInfo:
    ticker: str
    currency: str
    name: str | None
    isin: str | None
    asset_class: str


@dataclass
class Snapshot:
    as_of: dt.date
    provider: MarketDataProvider
    accounts: list[AccountInfo]
    core_accounts: list[ledger.Account]
    txs: list[ledger.Transaction]
    listings: dict[str, ListingInfo]
    series: dict[str, PriceSeries]
    fx_series: dict[str, PriceSeries]
    history: History | None
    positions: dict[tuple[int, str], Position]
    cash: dict[int, Decimal | None]
    warnings: list[str] = field(default_factory=list)
    generated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    # --- Cours et taux à une date ------------------------------------------

    def fx_at(self, currency: str, d: dt.date) -> Decimal:
        if currency == "EUR":
            return Decimal(1)
        s = self.fx_series.get(currency)
        if s is None:
            raise MissingCurrency(currency)
        v = _last_on_or_before(s.closes, d)
        if v is None:
            raise MissingCurrency(currency, f"aucun taux connu au {d.isoformat()}")
        return to_decimal(v[1], 8)

    def quote(self, ticker: str) -> tuple[Decimal | None, dt.date | None, bool, str | None]:
        """Cours retenu à `as_of` : (prix, date, non frais, source)."""
        h = self.history
        s = self.series.get(ticker)
        obs = _last_on_or_before(s.closes, self.as_of) if s is not None else None
        if obs is not None and (self.as_of - obs[0]).days <= MAX_STALE_DAYS:
            return to_decimal(obs[1]), obs[0], (self.as_of - obs[0]).days > STALE_AFTER_DAYS, s.source
        # Repli : prix de la dernière transaction, s'il est récent.
        if h is not None and ticker in h.prices and not pd.isna(h.prices[ticker].iloc[-1]):
            last_tx = max((t for t in self.txs if t.ticker == ticker and t.price is not None),
                          key=lambda t: t.date, default=None)
            if last_tx is not None:
                return last_tx.price, last_tx.date, True, TX_PRICE_SOURCE
        return None, obs[0] if obs else None, True, s.source if s is not None else None

    def fx_now(self, currency: str) -> Decimal | None:
        try:
            v = self.fx_at(currency, self.as_of)
        except MissingCurrency:
            return None
        if currency != "EUR":
            last = _last_on_or_before(self.fx_series[currency].closes, self.as_of)
            if last is None or (self.as_of - last[0]).days > MAX_STALE_DAYS:
                return None
        return v

    # --- Métadonnées --------------------------------------------------------

    @property
    def simulated(self) -> bool:
        return self.provider.simulated or any(s.simulated for s in self.series.values()) \
            or any(s.simulated for s in self.fx_series.values())

    def meta(self) -> schemas.Meta:
        groups: dict[tuple[str, bool], list[PriceSeries]] = defaultdict(list)
        for s in list(self.series.values()) + list(self.fx_series.values()):
            groups[(s.source, s.simulated)].append(s)
        sources = []
        for (name, sim), items in sorted(groups.items()):
            dates = [s.last_date for s in items if s.last_date]
            sources.append(schemas.SourceInfo(
                name=name, symbols=sorted(s.ticker for s in items),
                last_date=max(dates) if dates else None,
                fetched_at=max(s.fetched_at for s in items), simulated=sim))
        fallback = sorted({p.ticker for p in self.positions.values()
                           if p.is_open and self.quote(p.ticker)[3] == TX_PRICE_SOURCE})
        if fallback:
            sources.append(schemas.SourceInfo(name=TX_PRICE_SOURCE, symbols=fallback,
                                              last_date=None, fetched_at=None, simulated=False))
        return schemas.Meta(as_of=self.as_of, generated_at=self.generated_at, simulated=self.simulated,
                            provider=self.provider.name, sources=sources, warnings=self.warnings)


def _last_on_or_before(s: pd.Series, d: dt.date) -> tuple[dt.date, float] | None:
    s = s.loc[: pd.Timestamp(d)].dropna()
    if s.empty:
        return None
    return pd.Timestamp(s.index[-1]).date(), float(s.iloc[-1])


def snapshot(s: Session, provider: MarketDataProvider, as_of: dt.date | None = None) -> Snapshot:
    as_of = as_of or dt.date.today()
    orm_accounts, core_accounts, txs, orm_listings = load_ledger(s)
    accounts = [AccountInfo(a.id, a.name, a.kind, a.cash_mode, a.currency) for a in orm_accounts]
    listings = {t: ListingInfo(t, l.currency, l.instrument.name, l.instrument.isin, l.instrument.asset_class)
                for t, l in orm_listings.items()}
    s.rollback()          # fin de la lecture : le fournisseur peut écrire son cache
    warnings = ledger.validate(core_accounts, txs, {t: l.currency for t, l in listings.items()})
    txs = [t for t in txs if t.date <= as_of]

    series: dict[str, PriceSeries] = {}
    fx_series: dict[str, PriceSeries] = {}
    if txs:
        start = min(t.date for t in txs) - dt.timedelta(days=LOOKBACK_DAYS)
        for ticker in sorted({t.ticker for t in txs if t.ticker}):
            try:
                series[ticker] = provider.daily_closes(ticker, start, as_of)
            except (UnknownTicker, ProviderUnavailable) as e:
                warnings.append(str(e))
        currencies = {t.currency for t in txs} | {listings[t].currency for t in series if t in listings}
        for cur in sorted(currencies - {"EUR"}):
            try:
                fx_series[cur] = provider.fx_rates(cur, start, as_of)
            except (MissingCurrency, ProviderUnavailable) as e:
                warnings.append(str(e))

    snap = Snapshot(as_of, provider, accounts, core_accounts, txs, listings, series, fx_series,
                    None, {}, {}, warnings)
    if txs:
        snap.history = build_history(core_accounts, txs, {t: p.closes for t, p in series.items()},
                                     {c: p.closes for c, p in fx_series.items()}, end=as_of)
        warnings.extend(w for w in snap.history.warnings if w not in warnings)
    snap.positions = compute_positions(txs, snap.fx_at)
    snap.cash = cash_balances(core_accounts, txs, snap.fx_at)
    return snap


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------

def _sum(values) -> Decimal | None:
    total = Decimal(0)
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _weight(v: Decimal | None, total: Decimal | None) -> Decimal | None:
    if v is None or total is None or total == 0:
        return None
    return v / total


def _q(v: Decimal | None, exp: Decimal = CENT) -> Decimal | None:
    return None if v is None else v.quantize(exp)


def positions_out(snap: Snapshot) -> list[schemas.PositionOut]:
    names = {a.id: a.name for a in snap.accounts}
    rows = []
    for (acc, ticker), p in sorted(snap.positions.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        inst = snap.listings.get(ticker)
        price, price_date, stale, source = snap.quote(ticker) if p.is_open else (None, None, False, None)
        fx = snap.fx_now(p.currency) if p.is_open else None
        mv = p.market_value(price) if p.is_open else Decimal(0)
        mv_eur = p.market_value_eur(price, fx) if p.is_open else Decimal(0)
        unreal = p.unrealized(price) if p.is_open else None
        rows.append(schemas.PositionOut(
            account_id=acc, account_name=names.get(acc, str(acc)), ticker=ticker,
            name=inst.name if inst else None, isin=inst.isin if inst else None,
            asset_class=inst.asset_class if inst else "autre", currency=p.currency, is_open=p.is_open,
            quantity=p.quantity, pru=_q(p.pru, Decimal("0.0001")), pru_eur=_q(p.pru_eur, Decimal("0.0001")),
            cost=_q(p.cost), cost_eur=_q(p.cost_eur), price=price, price_date=price_date,
            price_stale=stale, price_source=source, fx_rate=fx,
            market_value=_q(mv), market_value_eur=_q(mv_eur),
            unrealized=_q(unreal), unrealized_eur=_q(p.unrealized_eur(price, fx)) if p.is_open else None,
            unrealized_pct=_q(unreal / p.cost, Decimal("0.0001")) if unreal is not None and p.cost else None,
            realized=_q(p.realized), realized_eur=_q(p.realized_eur), dividends=_q(p.dividends),
            dividends_eur=_q(p.dividends_eur), fees=_q(p.fees), weight=None))
    total = summary_total(snap, rows)
    for r in rows:
        if r.is_open:
            r.weight = _q(_weight(r.market_value_eur, total), Decimal("0.0001"))
    return rows


def summary_total(snap: Snapshot, rows: list[schemas.PositionOut]) -> Decimal | None:
    return _sum([r.market_value_eur for r in rows if r.is_open] + list(snap.cash.values()))


def _alloc(groups: dict[str, tuple[str, Decimal | None]], total: Decimal | None) -> list[schemas.AllocationItem]:
    items = [schemas.AllocationItem(key=k, label=lbl, value_eur=_q(v),
                                    weight=_q(_weight(v, total), Decimal("0.0001")))
             for k, (lbl, v) in groups.items()]
    return sorted(items, key=lambda i: (i.value_eur is None, -(i.value_eur or 0)))


def net_contributions(snap: Snapshot) -> Decimal | None:
    """Apports nets en euros (apports - retraits), selon la convention de chaque compte."""
    modes = {a.id: a.cash_mode for a in snap.core_accounts}
    total = Decimal(0)
    for t in snap.txs:
        f = ledger.external_flows(t, modes[t.account_id])
        if not (f.inflow or f.outflow):
            continue
        rate = transaction_rate(t, snap.fx_at)
        if rate is None:
            return None
        total += (f.inflow - f.outflow) * rate
    return _q(total)


def summary_out(snap: Snapshot) -> schemas.SummaryOut:
    rows = positions_out(snap)
    open_rows = [r for r in rows if r.is_open]
    total = summary_total(snap, rows)
    missing = sorted({f"{r.ticker} ({r.account_name})" for r in open_rows if r.market_value_eur is None})
    missing += [f"Espèces ({a.name})" for a in snap.accounts if a.id in snap.cash and snap.cash[a.id] is None]

    accounts, by_account = [], {}
    for a in snap.accounts:
        sec = _sum(r.market_value_eur for r in open_rows if r.account_id == a.id)
        cash = _q(snap.cash.get(a.id)) if a.id in snap.cash else None
        value = _sum([sec, cash]) if a.id in snap.cash else sec
        accounts.append(schemas.AccountValue(id=a.id, name=a.name, kind=a.kind,
                                             cash_mode=ledger.CashMode(a.cash_mode),
                                             value_eur=_q(value), securities_eur=_q(sec), cash_eur=cash))
        by_account[str(a.id)] = (a.name, value)

    by_asset: dict[str, list] = {}
    by_currency: dict[str, list] = defaultdict(list)
    by_class: dict[str, list] = defaultdict(list)
    for r in open_rows:
        key = r.isin or r.ticker                       # un même titre sur deux places : une ligne
        by_asset.setdefault(key, [r.name or r.ticker, []])[1].append(r.market_value_eur)
        by_currency[r.currency].append(r.market_value_eur)
        by_class[r.asset_class].append(r.market_value_eur)
    cash_total = _sum(snap.cash.values()) if snap.cash else None
    if snap.cash:
        by_asset["__cash__"] = ["Espèces", [cash_total]]
        by_currency["EUR"].append(cash_total)
        by_class["especes"].append(cash_total)

    class_labels = {"action": "Actions", "etf": "ETF", "crypto": "Crypto", "autre": "Autres",
                    "especes": "Espèces"}
    return schemas.SummaryOut(
        meta=snap.meta(), complete=not missing, missing=missing,
        total_value_eur=_q(total),
        securities_eur=_q(_sum(r.market_value_eur for r in open_rows)),
        cash_eur=_q(cash_total) if snap.cash else Decimal("0.00"),
        cost_eur=_q(_sum(r.cost_eur for r in open_rows)),
        unrealized_eur=_q(_sum(r.unrealized_eur for r in open_rows)),
        realized_eur=_q(_sum(r.realized_eur for r in rows)),
        dividends_eur=_q(_sum(r.dividends_eur for r in rows)),
        net_contributions_eur=net_contributions(snap),
        accounts=accounts,
        by_account=_alloc(by_account, total),
        by_asset=_alloc({k: (lbl, _sum(v)) for k, (lbl, v) in by_asset.items()}, total),
        by_currency=_alloc({k: (k, _sum(v)) for k, v in by_currency.items()}, total),
        by_class=_alloc({k: (class_labels.get(k, k), _sum(v)) for k, v in by_class.items()}, total),
    )


def _floats(s: pd.Series) -> list[float | None]:
    return [None if pd.isna(v) else round(float(v), 2) for v in s]


def history_out(snap: Snapshot) -> schemas.HistoryOut:
    h = snap.history
    if h is None:
        return schemas.HistoryOut(meta=snap.meta(), dates=[], value=[], net_contributions=[], accounts=[])
    net = (h.total["inflow"] - h.total["outflow"]).cumsum(skipna=False)
    return schemas.HistoryOut(
        meta=snap.meta(), dates=[d.date() for d in h.total.index], value=_floats(h.total["value"]),
        net_contributions=_floats(net),
        accounts=[schemas.SeriesOut(id=a.id, name=a.name, value=_floats(h.accounts[a.id]["value"]))
                  for a in snap.accounts])


def _twr(values, inflow, outflow) -> schemas.TwrOut:
    r = performance.twr(values, inflow, outflow)
    return schemas.TwrOut(total=r.total, annualized=r.annualized, start=r.start, end=r.end,
                          days=r.days, warnings=r.warnings)


def _mwr(values, inflow, outflow) -> schemas.MwrOut:
    r = performance.mwr(values, inflow, outflow)
    return schemas.MwrOut(rate=r.rate, annualized=r.annualized, start=r.start, end=r.end,
                          days=r.days, warnings=r.warnings)


def performance_out(snap: Snapshot) -> schemas.PerformanceOut:
    empty_twr = schemas.TwrOut(total=None, annualized=None, start=None, end=None, days=0,
                               warnings=["Aucune transaction."])
    empty_mwr = schemas.MwrOut(rate=None, annualized=False, start=None, end=None, days=0,
                               warnings=["Aucune transaction."])
    h = snap.history
    if h is None:
        total = schemas.PerformanceBlock(id=None, name="Portefeuille", cash_mode=None,
                                         twr=empty_twr, twr_securities=None, mwr=empty_mwr)
        return schemas.PerformanceOut(meta=snap.meta(), total=total, accounts=[])
    t = h.total
    total = schemas.PerformanceBlock(id=None, name="Portefeuille", cash_mode=None,
                                     twr=_twr(t["value"], t["inflow"], t["outflow"]), twr_securities=None,
                                     mwr=_mwr(t["value"], t["inflow"], t["outflow"]))
    blocks = []
    for a in snap.accounts:
        f = h.accounts[a.id]
        mode = ledger.CashMode(a.cash_mode)
        blocks.append(schemas.PerformanceBlock(
            id=a.id, name=a.name, cash_mode=mode,
            twr=_twr(f["value"], f["inflow"], f["outflow"]),
            twr_securities=(_twr(f["securities"], f["sleeve_inflow"], f["sleeve_outflow"])
                            if mode is ledger.CashMode.AVEC_ESPECES else None),
            mwr=_mwr(f["value"], f["inflow"], f["outflow"])))
    return schemas.PerformanceOut(meta=snap.meta(), total=total, accounts=blocks)
