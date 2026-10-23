"""
Jeu de transactions FICTIF pour le mode démo, construit sur les cours simulés.

Trois comptes, les deux conventions de flux, de l'USD et de la crypto :
- PEA (avec espèces) : 400 € versés chaque mois, DCA sur deux ETF ;
- CTO (avec espèces) : versements trimestriels, quelques actions dont une en USD ;
- Crypto (titres seuls) : 100 € de bitcoin par mois.
Le CTO détient aussi NVDA, divisée par 10 le 10/06/2024 (division simulée) : les
achats antérieurs sont saisis en prix d'origine, comme sur un relevé de courtier,
et l'application les ajuste au calcul.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from terminal.marketdata.base import MarketDataProvider

from . import models

START = dt.date(2021, 1, 4)

LISTINGS = [  # ticker, isin, nom, classe, devise
    ("PANX.PA", "FR0011871110", "ETF Nasdaq 100 (PEA) — démo", "etf", "EUR"),
    ("CW8.PA", "LU1681043599", "ETF MSCI World (PEA) — démo", "etf", "EUR"),
    ("AAPL", "US0378331005", "Apple — démo", "action", "USD"),
    ("MC.PA", "FR0000121014", "LVMH — démo", "action", "EUR"),
    ("ASML.AS", "NL0010273215", "ASML — démo", "action", "EUR"),
    ("BTC-EUR", None, "Bitcoin — démo", "crypto", "EUR"),
    ("NVDA", "US67066G1040", "NVIDIA — démo", "action", "USD"),
]


def _months(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def seed(s: Session, provider: MarketDataProvider, today: dt.date | None = None) -> bool:
    """Remplit une base vide. Renvoie False si la base contient déjà des comptes."""
    if s.scalar(select(models.Account).limit(1)) is not None:
        return False
    today = today or dt.date.today()
    # Cours d'abord : le cache écrit dans sa propre session, qui ne doit pas
    # attendre une écriture ouverte ici (SQLite n'a qu'un écrivain à la fois).
    lookback = START - dt.timedelta(days=10)
    closes = {t[0]: provider.daily_closes(t[0], lookback, today).closes for t in LISTINGS}
    usd = provider.fx_rates("USD", lookback, today).closes
    pea = models.Account(name="PEA Fortuneo (démo)", broker="Fortuneo", kind="PEA", cash_mode="avec_especes")
    cto = models.Account(name="CTO Trade Republic (démo)", broker="Trade Republic", kind="CTO",
                         cash_mode="avec_especes")
    cry = models.Account(name="Crypto (démo)", broker=None, kind="CRYPTO", cash_mode="titres_seuls")
    s.add_all([pea, cto, cry])
    listings = {}
    for ticker, isin, name, cls, cur in LISTINGS:
        listings[ticker] = models.Listing(ticker=ticker, currency=cur,
                                          instrument=models.Instrument(isin=isin, name=name, asset_class=cls))
    s.add_all(listings.values())
    s.flush()


    def px(ticker: str, d: dt.date) -> tuple[dt.date, Decimal]:
        s_ = closes[ticker].loc[:str(d)]
        return s_.index[-1].date(), Decimal(repr(round(float(s_.iloc[-1]), 2)))

    def add(acc, kind, d, listing=None, **kw):
        s.add(models.Transaction(account_id=acc.id, listing_id=listing.id if listing else None, date=d,
                                 type=kind, currency=kw.pop("currency", "EUR"), **kw))

    for m in _months(START, today):
        d = m + dt.timedelta(days=4)
        if d > today:
            break
        add(pea, "DEPOT", d, amount=Decimal(400))
        for t in ("PANX.PA", "CW8.PA"):
            day, p = px(t, d)
            q = (Decimal(200) / p).quantize(Decimal(1), ROUND_DOWN)        # pas de fraction au PEA
            if q > 0:
                add(pea, "ACHAT", d, listings[t], quantity=q, price=p, fees=Decimal("0.00"))
        day, p = px("BTC-EUR", d)
        q = ((Decimal(100) - Decimal("1.50")) / p).quantize(Decimal("0.00000001"), ROUND_DOWN)
        add(cry, "ACHAT", d, listings["BTC-EUR"], quantity=q, price=p, fees=Decimal("1.50"))
        if m.month in (1, 4, 7, 10):
            add(cto, "DEPOT", d, amount=Decimal(1500))
            for t, budget in (("MC.PA", 500), ("ASML.AS", 500)):
                day, p = px(t, d)
                q = (Decimal(budget) / p).quantize(Decimal("0.0001"), ROUND_DOWN)
                add(cto, "ACHAT", d, listings[t], quantity=q, price=p, fees=Decimal(1))
            day, p = px("AAPL", d)
            rate = Decimal(repr(round(float(usd.loc[:str(d)].iloc[-1]), 4)))
            q = (Decimal(450) / (p * rate)).quantize(Decimal("0.0001"), ROUND_DOWN)
            add(cto, "ACHAT", d, listings["AAPL"], quantity=q, price=p, fees=Decimal(1), currency="USD",
                fx_rate=rate)
        if m.month == 5 and m.year > START.year:
            add(cto, "DIVIDENDE", d, listings["MC.PA"], amount=Decimal("18.40"), withholding=Decimal("7.90"))
    # NVDA : 2 actions avant la division (prix d'origine = cours ajusté x 10), 10 après.
    from terminal.marketdata.simulated import SIM_SPLITS
    split_day, n, m_ = SIM_SPLITS["NVDA"][0]
    for d, q in ((dt.date(2023, 3, 15), Decimal(2)), (dt.date(2024, 9, 16), Decimal(10))):
        if d <= today:
            day, p = px("NVDA", d)
            if d < split_day:
                p = p * n / m_
            rate = Decimal(repr(round(float(usd.loc[:str(d)].iloc[-1]), 4)))
            # Versement couvrant l'achat, arrondi à l'euro supérieur : le solde reste positif.
            add(cto, "DEPOT", d, amount=((q * p + 1) * rate).quantize(Decimal(1), ROUND_UP))
            add(cto, "ACHAT", d, listings["NVDA"], quantity=q, price=p, fees=Decimal(1), currency="USD",
                fx_rate=rate)
    # Une prise de bénéfice partielle sur ASML.
    sell = dt.date(2024, 3, 12)
    if sell <= today:
        day, p = px("ASML.AS", sell)
        add(cto, "VENTE", sell, listings["ASML.AS"], quantity=Decimal("2.0000"), price=p, fees=Decimal(1))
    s.commit()
    return True
