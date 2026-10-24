"""
Page Valorisation : DCF inversé des actions détenues (terminal/dcf.py).

Données : comptes annuels du fournisseur (cache en base), complétés ou corrigés par les
saisies manuelles du titre, qui priment et restent signalées. Hypothèses : réglages, puis
profil du titre. Rien n'est transmis à l'extérieur : seules des hypothèses et des saisies
locales sont écrites.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from terminal import dcf, risk
from terminal import metrics as m
from terminal.benchmark import to_eur
from terminal.errors import MissingCurrency, ProviderUnavailable, UnknownTicker
from terminal.marketdata.base import FUNDAMENTAL_FIELDS, Fundamentals, MarketDataProvider, PriceSeries
from terminal.marketdata.rates import RateProvider

from .. import models, schemas
from ..settings_store import AnalysisSettings
from .portfolio import Snapshot, positions_out
from .risk import reference_returns

BETA_YEARS = 5
MIN_BETA_WEEKS = 104
FX_LOOKBACK = dt.timedelta(days=10)
YIELD_LOOKBACK = dt.timedelta(days=15)


def _fr_date(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def _pct(x: float, digits: int = 2) -> str:
    return f"{x * 100:.{digits}f}".replace(".", ",") + " %"


def _num(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}".replace(".", ",").replace("-", "−")


def _r(x, d=6):
    return None if x is None or not np.isfinite(x) else round(float(x), d)


# ---------------------------------------------------------------------------
# Titres détenus, profil, données fusionnées
# ---------------------------------------------------------------------------

@dataclass
class Title:
    instrument_id: int
    ticker: str                    # cotation dont on lit cours et comptes
    name: str
    isin: str | None
    asset_class: str
    quote_currency: str


def held_titles(s: Session, snap: Snapshot) -> list[Title]:
    """Titres en position ouverte, un par instrument (même titre sur deux comptes = une fiche)."""
    out: dict[int, Title] = {}
    for p in positions_out(snap):
        if not p.is_open:
            continue
        listing = s.scalar(select(models.Listing).where(models.Listing.ticker == p.ticker))
        if listing is None or listing.instrument_id in out:
            continue
        out[listing.instrument_id] = Title(listing.instrument_id, p.ticker, p.name or p.ticker, p.isin,
                                           p.asset_class, p.currency)
    return list(out.values())


def find_title(s: Session, snap: Snapshot, ticker: str) -> Title | None:
    return next((t for t in held_titles(s, snap) if t.ticker == ticker.upper()), None)


def proposed_standard(t: Title) -> str:
    """Valeur proposée : US GAAP pour une cotation américaine (sans suffixe de place), IFRS sinon."""
    return "us_gaap" if t.quote_currency == "USD" and "." not in t.ticker and "-" not in t.ticker else "ifrs"


@dataclass
class Merged:
    table: pd.DataFrame
    manual: dict[tuple[pd.Timestamp, str], models.FundamentalOverride] = field(default_factory=dict)


def merged_table(s: Session, f: Fundamentals | None, instrument_id: int) -> Merged:
    """Comptes du fournisseur + saisies manuelles du titre (elles priment, y compris sur un exercice absent)."""
    table = f.table.copy() if f is not None else pd.DataFrame(columns=list(FUNDAMENTAL_FIELDS), dtype=float)
    overrides = s.scalars(select(models.FundamentalOverride)
                          .where(models.FundamentalOverride.instrument_id == instrument_id)).all()
    manual = {}
    for o in overrides:
        d = pd.Timestamp(o.fiscal_end)
        if d not in table.index:
            table.loc[d] = np.nan
        table.loc[d, o.field] = float(o.value)
        manual[(d, o.field)] = o
    return Merged(table.sort_index().astype(float), manual)


def assumptions(settings: AnalysisSettings, profile: models.ValuationProfile | None, t: Title,
                k: float) -> tuple[dcf.Assumptions, list[str]]:
    p = profile
    custom = []

    def pick(attr, default, conv=lambda x: x):
        v = getattr(p, attr) if p is not None else None
        if v is None:
            return default
        custom.append(attr)
        return conv(v)

    a = dcf.Assumptions(
        k=k,
        horizon=pick("horizon", settings.horizon),
        g_term=pick("g_term", float(settings.g_term), float),
        fcf_years=pick("fcf_years", settings.fcf_years),
        sbc_deduct=pick("sbc_deduct", settings.sbc_deduct),
        standard=(p.standard if p is not None and p.standard else proposed_standard(t)),
        interest_class=(p.interest_class if p is not None and p.interest_class else "exploitation"),
        statutory_tax=pick("statutory_tax", None, float),
        accept_interest_approx=bool(p and p.accept_interest_approx),
        accept_minority_approx=bool(p and p.accept_minority_approx),
    )
    return a, custom


# ---------------------------------------------------------------------------
# Cours, change, coût du capital
# ---------------------------------------------------------------------------

def _last(s: pd.Series, d: dt.date, max_age: dt.timedelta) -> tuple[dt.date, float] | None:
    s = s.loc[: pd.Timestamp(d)].dropna()
    if s.empty or d - s.index[-1].date() > max_age:
        return None
    return s.index[-1].date(), float(s.iloc[-1])


def fx_eur(provider: MarketDataProvider, cur: str, d: dt.date, sources: list) -> float | None:
    if cur == "EUR":
        return 1.0
    try:
        ps = provider.fx_rates(cur, d - FX_LOOKBACK, d)
    except (MissingCurrency, ProviderUnavailable):
        return None
    sources.append(ps)
    v = _last(ps.closes, d, FX_LOOKBACK)
    return v[1] if v else None


def k_common(rates: RateProvider, settings: AnalysisSettings, cur: str, d: dt.date,
             sources: list) -> tuple[schemas.KOut, float | None]:
    """k commun de la devise : saisi dans les réglages, sinon taux à 10 ans + prime de risque (β = 1)."""
    erp = float(settings.erp)
    if cur in settings.k_manual:
        k = float(settings.k_manual[cur])
        return schemas.KOut(k=_r(k), label=f"commun {cur}", detail=f"k saisi dans les réglages pour {cur}"), None
    try:
        ps = rates.long_yield(cur, d - YIELD_LOOKBACK, d)
    except ProviderUnavailable as e:
        return schemas.KOut(k=None, label=f"commun {cur}", detail="",
                            error=f"Taux long {cur} indisponible ({e}) : saisissez un k pour {cur} dans les "
                                  "réglages."), None
    sources.append(ps)
    v = _last(ps.closes, d, YIELD_LOOKBACK)
    if v is None:
        return schemas.KOut(k=None, label=f"commun {cur}", detail="",
                            error=f"Aucun taux long {cur} récent : saisissez un k pour {cur} dans les réglages."), None
    rf = v[1] / 100
    detail = (f"taux d'État à 10 ans {_pct(rf)} ({ps.source}, au {_fr_date(v[0])}) + prime de risque "
              f"{_pct(erp, 1)}, β = 1")
    return schemas.KOut(k=_r(dcf.common_k(rf, erp)), label=f"commun {cur}", detail=detail), rf


def beta(provider: MarketDataProvider, settings: AnalysisSettings, t: Title, d: dt.date,
         sources: list) -> float | None:
    """β de Dimson hebdomadaire sur 5 ans, en EUR, contre la seconde référence (MSCI World)."""
    base = d - dt.timedelta(days=round(365.25 * BETA_YEARS))
    grid = risk.business_grid(base, d)
    try:
        closes = provider.daily_closes(t.ticker, base - FX_LOOKBACK, d)
        fx = provider.fx_rates(t.quote_currency, base - FX_LOOKBACK, d) if t.quote_currency != "EUR" else None
    except (UnknownTicker, ProviderUnavailable, MissingCurrency):
        return None
    stock = risk.index_returns(to_eur(closes.closes, fx.closes if fx is not None else None), grid, base)
    ref = reference_returns(provider, settings.reference_2, base, d, grid, [], sources)
    ws, wr = risk.to_weekly(stock)[0], risk.to_weekly(ref)[0]
    both = pd.concat([ws, wr], axis=1).dropna()
    if len(both) < MIN_BETA_WEEKS:
        return None
    b = m.dimson_beta(both.iloc[:, 0], both.iloc[:, 1])
    return float(b) if np.isfinite(b) else None


def k_capm(rf: float | None, settings: AnalysisSettings, b: float | None, ev: dcf.EnterpriseValue | None,
           table: pd.DataFrame, a: dcf.Assumptions, tax: float | None) -> schemas.KOut:
    label = "MEDAF"
    if rf is None:
        return schemas.KOut(k=None, label=label, detail="", error="Taux long indisponible.")
    if ev is None:
        return schemas.KOut(k=None, label=label, detail="", error="Valeur d'entreprise non calculable.")
    debt = ev.debt
    # Dette moyenne des deux derniers bilans, selon la même règle que la VE.
    hist = table["total_debt"]
    if a.standard == "us_gaap" and table["lease_liabilities"].notna().any():
        hist = hist - table["lease_liabilities"]
    avg = float(hist.dropna().iloc[-2:].mean()) if hist.notna().any() else None
    interest = table["interest_expense"].iloc[-1] if len(table) else np.nan
    c = dcf.capm_k(rf, float(settings.erp), b, ev.market_cap, debt,
                   None if pd.isna(interest) else float(interest), avg, tax)
    if c.k is None:
        return schemas.KOut(k=None, label=label, detail="", error=c.reason)
    parts = [f"ke = {_pct(rf)} + {_num(c.beta_adj)} × {_pct(float(settings.erp), 1)} = {_pct(c.ke)} "
             f"(β de Dimson {_num(c.beta_raw)}, ajusté par Blume, hebdomadaire sur {BETA_YEARS} ans)"]
    if c.kd_after_tax is not None:
        parts.append(f"kd après impôt {_pct(c.kd_after_tax)}, fonds propres {_pct(c.weight_equity, 0)} de "
                     "capitalisation + dette")
    return schemas.KOut(k=_r(c.k), label=label, detail=" ; ".join(parts))


# ---------------------------------------------------------------------------
# Fiche
# ---------------------------------------------------------------------------

def _growth(g: dcf.Growth | None) -> schemas.GrowthOut | None:
    if g is None:
        return None
    return schemas.GrowthOut(value=_r(g.value), status=g.status, years=g.years, n_points=g.n_points,
                             start=g.start.date() if g.start is not None else None,
                             end=g.end.date() if g.end is not None else None)


def _missing(items: list[dcf.MissingItem]) -> list[schemas.MissingOut]:
    return [schemas.MissingOut(fiscal_end=i.fiscal_end.date() if i.fiscal_end is not None else None, field=i.field,
                               label=i.label, remedy=i.remedy) for i in items]


def _meta(snap: Snapshot, f: Fundamentals | None, extra: list[PriceSeries]) -> schemas.Meta:
    meta = snap.meta()
    for ps in extra:
        meta.sources.append(schemas.SourceInfo(name=ps.source, symbols=[ps.ticker], last_date=ps.last_date,
                                               fetched_at=ps.fetched_at, simulated=ps.simulated))
    if f is not None:
        last = f.table.index[-1].date() if len(f.table) else None
        meta.sources.append(schemas.SourceInfo(name=f"{f.source} (comptes annuels)", symbols=[f.ticker],
                                               last_date=last, fetched_at=f.fetched_at, simulated=f.simulated))
        meta.simulated = meta.simulated or f.simulated
    meta.simulated = meta.simulated or any(ps.simulated for ps in extra)
    seen, unique = set(), []
    for src in meta.sources:
        key = (src.name, tuple(src.symbols))
        if key not in seen:
            seen.add(key)
            unique.append(src)
    meta.sources = unique
    return meta


def analyze(s: Session, snap: Snapshot, provider: MarketDataProvider, rates: RateProvider,
            settings: AnalysisSettings, t: Title, detailed: bool = True) -> schemas.ValuationOut:
    """
    Fiche d'un titre. `detailed=False` (tableau récapitulatif) : k commun seulement, sans MEDAF ni
    sensibilité ni cours.
    """
    sources: list[PriceSeries] = []
    warnings: list[str] = []
    out = dict(ticker=t.ticker, name=t.name, isin=t.isin, asset_class=t.asset_class, status="ok", reason=None,
               missing=[], sector=None, industry=None, fundamentals_source=None, fundamentals_fetched_at=None,
               fundamentals_simulated=False, accounts_currency=None, years=[], profile=None, fcff_rule=None,
               fcff0=None, fcf_window=[], tax_rate=None, tax_source=None, ev=None, k_used=None, k_common=None,
               k_capm=None, g=None, sentence=None, growth_fcff=None, growth_revenue=None, sensitivity=[],
               prices=[], warnings=warnings)

    def done(f: Fundamentals | None = None) -> schemas.ValuationOut:
        return schemas.ValuationOut(meta=_meta(snap, f, sources), **out)

    # Périmètre : la classe saisie suffit à exclure fonds et crypto, sans appel au fournisseur.
    early = dcf.eligibility(t.asset_class, None, None, False) if t.asset_class != "action" else None
    if early:
        out.update(status="exclue", reason=early)
        return done()
    try:
        f = provider.fundamentals(t.ticker)
    except (UnknownTicker, ProviderUnavailable) as e:
        out.update(status="impossible", reason=f"Comptes annuels indisponibles : {e}")
        return done()
    profile = s.get(models.ValuationProfile, t.instrument_id)
    out.update(sector=f.sector, industry=f.industry, fundamentals_source=f.source,
               fundamentals_fetched_at=f.fetched_at, fundamentals_simulated=f.simulated)
    reason = dcf.eligibility(t.asset_class, f.quote_type, f.industry, profile.financial if profile else None)
    if reason:
        out.update(status="exclue", reason=reason)
        return done(f)

    merged = merged_table(s, f, t.instrument_id)
    table = merged.table
    cur = f.currency
    if cur is None:
        out.update(status="impossible", reason="Devise des comptes inconnue chez le fournisseur.")
        return done(f)
    out["accounts_currency"] = cur

    # Coût du capital commun (le tableau récapitulatif n'utilise que lui).
    kc, rf = k_common(rates, settings, cur, snap.as_of, sources)
    out["k_common"] = kc
    k_custom = float(profile.k) if detailed and profile is not None and profile.k is not None else None
    a, custom = assumptions(settings, profile, t, kc.k if kc.k is not None else float("nan"))
    out["profile"] = schemas.ProfileOut(
        standard=a.standard, standard_label=dcf.STANDARDS[a.standard],
        standard_proposed=not (profile and profile.standard), interest_class=a.interest_class,
        financial=profile.financial if profile else None, k=k_custom, horizon=a.horizon, g_term=a.g_term,
        fcf_years=a.fcf_years, sbc_deduct=a.sbc_deduct, statutory_tax=a.statutory_tax,
        accept_interest_approx=a.accept_interest_approx, accept_minority_approx=a.accept_minority_approx,
        custom=custom + (["k"] if k_custom is not None else []))
    if not (profile and profile.standard):
        warnings.append(f"Norme comptable proposée ({dcf.STANDARDS[a.standard]}) d'après la cotation : vérifiez-la "
                        "dans le rapport annuel, avec le classement des intérêts versés.")

    # Cours et change (devise de cotation -> devise des comptes).
    price, price_date, _, _ = snap.quote(t.ticker)
    if t.ticker in snap.series:
        sources.append(snap.series[t.ticker])
    fx_q, fx_a = fx_eur(provider, t.quote_currency, snap.as_of, sources), fx_eur(provider, cur, snap.as_of, sources)
    fx = fx_q / fx_a if fx_q is not None and fx_a is not None else float("nan")

    # FCFF et VE : on rassemble TOUTES les données manquantes avant de répondre.
    missing: list[dcf.MissingItem] = []
    fr = ev = None
    try:
        fr = dcf.fcff(table, a)
    except dcf.Missing as e:
        missing += e.items
    except dcf.DCFError as e:
        out.update(status="impossible", reason=str(e))
    try:
        ev = dcf.enterprise_value(table, float(price) if price is not None else float("nan"), fx, a)
    except dcf.Missing as e:
        missing += e.items
    except dcf.DCFError as e:
        if out["status"] == "ok":
            out.update(status="impossible", reason=str(e))

    # Tableau des comptes (affiché même quand le calcul est bloqué).
    fcff_by_year = fr.table["fcff"] if fr is not None else pd.Series(dtype=float)
    for d, row in table.iterrows():
        cells = {}
        for col in FUNDAMENTAL_FIELDS:
            o = merged.manual.get((d, col))
            v = row[col]
            cells[col] = schemas.FundamentalCell(
                value=None if pd.isna(v) else (o.value if o is not None else Decimal(repr(float(v)))),
                manual=o is not None, note=o.note if o is not None else None,
                entered_at=o.entered_at if o is not None else None)
        fv = fcff_by_year.get(d, np.nan)
        out["years"].append(schemas.FundamentalYear(fiscal_end=d.date(), values=cells, fcff=_r(fv, 2)))
    out["growth_revenue"] = _growth(dcf.historical_growth(table["revenue"]))

    if missing:
        out.update(status="bloquee", missing=_missing(missing),
                   reason="Données manquantes : saisissez-les à la main (ou acceptez l'approximation proposée).")
    if fr is not None:
        warnings.extend(fr.warnings)
        out.update(fcff_rule=fr.rule, fcff0=_r(fr.fcff0, 2), fcf_window=[d.date() for d in fr.window],
                   tax_rate=_r(fr.tax_rate), tax_source=fr.tax_source,
                   growth_fcff=_growth(dcf.historical_growth(fr.table["fcff"])))
    if ev is not None:
        warnings.extend(ev.warnings)
        out["ev"] = schemas.EvOut(price=ev.price, price_date=price_date, price_currency=t.quote_currency, fx=_r(ev.fx, 8),
                                  accounts_currency=cur, shares=ev.shares, market_cap=_r(ev.market_cap, 0),
                                  debt=ev.debt, debt_rule=ev.debt_rule, cash=ev.cash, minority=ev.minority,
                                  ev=_r(ev.ev, 0), balance_date=ev.balance_date.date())
        if price_date is not None and (price_date - ev.balance_date.date()).days > 31:
            warnings.append(f"Décalage de dates : cours du {_fr_date(price_date)}, dette, trésorerie et nombre "
                            f"d'actions au bilan du {_fr_date(ev.balance_date.date())}.")

    # Prix (fiche seulement) : clôtures hebdomadaires sur 5 ans, devise de cotation.
    if detailed:
        try:
            ps = provider.daily_closes(t.ticker, snap.as_of - dt.timedelta(days=round(365.25 * 5)), snap.as_of)
            w = ps.closes.resample("W-FRI").last().dropna()
            out["prices"] = [schemas.PricePoint(time=d.date(), value=round(float(v), 4)) for d, v in w.items()]
        except (UnknownTicker, ProviderUnavailable):
            warnings.append("Historique de cours indisponible.")

    if out["status"] != "ok":
        return done(f)

    # g implicite avec chaque k.
    def solve(k: schemas.KOut) -> schemas.KOut:
        if k.k is None:
            return k
        try:
            k.g = _r(dcf.implied_growth(fr.fcff0, ev.ev, k.k, a.horizon, a.g_term))
        except dcf.DCFError as e:
            k.error = str(e)
        return k

    out["k_common"] = solve(kc)
    if detailed:
        b = beta(provider, settings, t, snap.as_of, sources)
        tax = fr.tax_rate
        if tax is None:
            try:
                tax = dcf.tax_rate(table, fr.window, a.statutory_tax)[0]
            except dcf.DCFError:
                tax = None
        out["k_capm"] = solve(k_capm(rf, settings, b, ev, table, a, tax))
    if k_custom is not None:
        used = solve(schemas.KOut(k=k_custom, label="personnalisé", detail="k saisi sur la fiche"))
    elif detailed and settings.k_mode == "medaf" and out["k_capm"].k is not None:
        used = out["k_capm"]
    else:
        used = out["k_common"]
        if detailed and settings.k_mode == "medaf":
            warnings.append("k MEDAF non calculable : le k commun est utilisé.")
    out["k_used"] = used
    if used.k is None:
        out.update(status="impossible", reason=used.error or "Coût du capital non défini.")
        return done(f)
    if used.g is None:
        out.update(status="impossible", reason=used.error)
        return done(f)
    out["g"] = used.g
    out["sentence"] = dcf.sentence(used.g, a.horizon, a.g_term, used.k)
    if detailed:
        out["sensitivity"] = [[schemas.SensiCell(k=_r(c.k), g_term=c.g_term, g=_r(c.g), reason=c.reason) for c in row]
                              for row in dcf.sensitivity(fr.fcff0, ev.ev, used.k, a.horizon)]
    return done(f)


# ---------------------------------------------------------------------------
# Tableau récapitulatif
# ---------------------------------------------------------------------------

def summary_out(s: Session, snap: Snapshot, provider: MarketDataProvider, rates: RateProvider,
                settings: AnalysisSettings) -> schemas.ValuationSummaryOut:
    rows, others, metas = [], [], []
    for t in held_titles(s, snap):
        v = analyze(s, snap, provider, rates, settings, t, detailed=False)
        metas.append(v.meta)
        kc = v.k_common
        g = kc.g if kc is not None and v.status == "ok" else None
        r = schemas.ValuationRow(
            ticker=v.ticker, name=v.name, status=v.status if g is not None or v.status != "ok" else "impossible",
            reason=v.reason if v.status != "ok" else (kc.error if kc is not None and g is None else None),
            g=g, k=kc.k if kc is not None else None, k_label=kc.label if kc is not None else None,
            growth_fcff=v.growth_fcff, growth_revenue=v.growth_revenue,
            ev_multiple=_r(v.ev.ev / v.fcff0, 2) if v.ev is not None and v.fcff0 else None,
            balance_date=v.ev.balance_date if v.ev is not None else None,
            price_date=v.ev.price_date if v.ev is not None else None,
            manual=any(c.manual for y in v.years for c in y.values.values()),
            approximations=bool(v.profile and (v.profile.accept_interest_approx or v.profile.accept_minority_approx)))
        (rows if r.g is not None else others).append(r)
    rows.sort(key=lambda r: r.g, reverse=True)
    order = {"bloquee": 0, "impossible": 1, "exclue": 2}
    others.sort(key=lambda r: (order.get(r.status, 3), r.name))
    meta = snap.meta()
    for mm in metas:
        for src in mm.sources:
            if all((src.name, src.symbols) != (x.name, x.symbols) for x in meta.sources):
                meta.sources.append(src)
        meta.simulated = meta.simulated or mm.simulated
    return schemas.ValuationSummaryOut(meta=meta, horizon=settings.horizon, g_term=float(settings.g_term),
                                       rows=rows, others=others)
