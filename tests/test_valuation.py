"""
Valorisation quotidienne et conventions de flux.

Les tests clés : les deux conventions donnent le même TWR des titres, et
aucun flux n'est compté deux fois.
"""

import numpy as np
import pandas as pd
import pytest

from _factories import CASH, SECU, day, prices, tx
from terminal import performance as pf
from terminal.errors import LedgerError
from terminal.ledger import validate
from terminal.valuation import build_history

ACCOUNTS = [CASH, SECU]
# Cours de AAA (EUR) : j0 100, j1 110, j2 99, j3 120, j4 120.
PX = {"AAA": prices(100, 110, 99, 120, 120)}


def trades(acc):
    return [tx("ACHAT", 0, acc=acc, ticker="AAA", q=10, p=100, fees=1),
            tx("ACHAT", 1, acc=acc, ticker="AAA", q=5, p=110, fees=1),
            tx("DIVIDENDE", 2, acc=acc, ticker="AAA", amount=10),
            tx("VENTE", 3, acc=acc, ticker="AAA", q=5, p=120, fees=1)]


def test_securities_twr_identical_in_both_conventions():
    # Même historique d'achats, ventes et dividende :
    # - compte 1 « avec espèces », alimenté par un dépôt de 5 000 qui dort en partie ;
    # - compte 2 « titres seuls ».
    hist = [tx("DEPOT", 0, acc=CASH, amount=5000)] + trades(CASH) + trades(SECU)
    validate(ACCOUNTS, hist)
    h = build_history(ACCOUNTS, hist, PX, {}, end=day(4))
    a, b = h.accounts[CASH.id], h.accounts[SECU.id]

    sleeve = pf.twr(a["securities"], a["sleeve_inflow"], a["sleeve_outflow"])
    secu = pf.twr(b["value"], b["inflow"], b["outflow"])
    assert sleeve.total == pytest.approx(secu.total, abs=1e-12)
    pd.testing.assert_series_equal(sleeve.returns, secu.returns)

    # Calcul à la main du TWR titres :
    # j0 : apport 1 001, valeur 1 000                r = 1000/1001 - 1
    # j1 : apport 551, valeur 15 x 110 = 1 650       r = 1650/(1000 + 551) - 1
    # j2 : retrait 10 (dividende), valeur 15 x 99    r = (1485 + 10)/1650 - 1
    # j3 : retrait 599 (vente), valeur 10 x 120      r = (1200 + 599)/1485 - 1
    # j4 : valeur inchangée                          r = 0
    expected = (1000 / 1001) * (1650 / 1551) * (1495 / 1650) * (1799 / 1485) - 1
    assert secu.total == pytest.approx(expected, abs=1e-12)

    # Le TWR du compte avec espèces diffère : 5 000 d'espèces diluent la performance.
    account = pf.twr(a["value"], a["inflow"], a["outflow"])
    assert abs(account.total - secu.total) > 1e-3


def test_account_twr_identical_when_every_deposit_is_invested_same_day():
    # Chaque dépôt couvre exactement l'achat et ses frais : il ne reste jamais d'espèces.
    hist = [tx("DEPOT", 0, acc=CASH, amount=1001),
            tx("ACHAT", 0, acc=CASH, ticker="AAA", q=10, p=100, fees=1),
            tx("DEPOT", 1, acc=CASH, amount=551),
            tx("ACHAT", 1, acc=CASH, ticker="AAA", q=5, p=110, fees=1),
            tx("ACHAT", 0, acc=SECU, ticker="AAA", q=10, p=100, fees=1),
            tx("ACHAT", 1, acc=SECU, ticker="AAA", q=5, p=110, fees=1)]
    h = build_history(ACCOUNTS, hist, PX, {}, end=day(4))
    a, b = h.accounts[CASH.id], h.accounts[SECU.id]
    assert (a["cash"].abs() < 1e-9).all()
    ta = pf.twr(a["value"], a["inflow"], a["outflow"])
    tb = pf.twr(b["value"], b["inflow"], b["outflow"])
    assert ta.total == pytest.approx(tb.total, abs=1e-12)


def test_no_double_counting_of_flows():
    # Compte avec espèces : seuls les dépôts et retraits sont des flux externes.
    hist = [tx("DEPOT", 0, amount=3000), tx("ACHAT", 0, ticker="AAA", q=10, p=100, fees=2),
            tx("VENTE", 3, ticker="AAA", q=5, p=120), tx("DIVIDENDE", 2, ticker="AAA", amount=7),
            tx("FRAIS", 3, amount=5), tx("RETRAIT", 4, amount=400)]
    h = build_history(ACCOUNTS, hist, PX, {}, end=day(4))
    a = h.accounts[CASH.id]
    assert a["inflow"].sum() == pytest.approx(3000)
    assert a["outflow"].sum() == pytest.approx(400)
    assert a["inflow"][a["inflow"] > 0].index.tolist() == [pd.Timestamp(day(0))]
    # Espèces : 3000 - 1002 + 7 + 600 - 5 - 400 = 2200 ; titres : 5 x 120 = 600.
    assert a["cash"].iloc[-1] == pytest.approx(2200)
    assert a["value"].iloc[-1] == pytest.approx(2800)
    # Total du portefeuille = somme des comptes, flux compris : pas de doublon.
    assert h.total["inflow"].sum() == pytest.approx(3000)


def test_deposit_invested_same_day_without_price_move_has_zero_return():
    # Dépôt 1 000, achat 10 à 100 le même jour, clôture 100.
    # Bon calcul : r = 1000 / (0 + 1000) - 1 = 0.
    # Si l'achat était aussi compté comme apport : r = 1000 / 2000 - 1 = -50 %.
    hist = [tx("DEPOT", 0, amount=1000), tx("ACHAT", 0, ticker="AAA", q=10, p=100)]
    h = build_history(ACCOUNTS, hist, {"AAA": prices(100)}, {}, end=day(0))
    a = h.accounts[CASH.id]
    assert pf.twr(a["value"], a["inflow"], a["outflow"]).total == pytest.approx(0.0, abs=1e-15)


def test_deposit_in_securities_only_account_is_rejected_before_valuation():
    with pytest.raises(LedgerError):
        validate(ACCOUNTS, [tx("DEPOT", 0, acc=SECU, amount=100)])


def test_securities_only_fees_are_contributions():
    # Frais de garde de 10 payés de l'extérieur sur un compte titres seuls :
    # apport consommé, la valeur ne bouge pas, le rendement du jour est négatif.
    hist = [tx("ACHAT", 0, acc=SECU, ticker="AAA", q=10, p=100), tx("FRAIS", 1, acc=SECU, amount=10)]
    h = build_history(ACCOUNTS, hist, {"AAA": prices(100, 100)}, {}, end=day(1))
    b = h.accounts[SECU.id]
    res = pf.twr(b["value"], b["inflow"], b["outflow"])
    assert res.returns.iloc[-1] == pytest.approx(1000 / 1010 - 1)


def test_usd_position_converted_with_daily_rate():
    hist = [tx("ACHAT", 0, acc=SECU, ticker="US1", q=2, p=50, cur="USD")]
    fx = {"USD": prices(0.9, 0.8)}
    h = build_history(ACCOUNTS, hist, {"US1": prices(50, 60)}, fx, end=day(1))
    b = h.accounts[SECU.id]
    # j0 : 2 x 50 x 0,9 = 90 ; j1 : 2 x 60 x 0,8 = 96. Apport 90 (taux de marché du jour).
    assert b["value"].tolist() == pytest.approx([90, 96])
    assert b["inflow"].iloc[0] == pytest.approx(90)


def test_cash_account_settles_usd_trade_at_broker_rate():
    hist = [tx("DEPOT", 0, amount=1000),
            tx("ACHAT", 0, ticker="US1", q=2, p=50, cur="USD", fees=1, fx="0.92")]
    h = build_history(ACCOUNTS, hist, {"US1": prices(50)}, {"USD": prices(0.9)}, end=day(0))
    a = h.accounts[CASH.id]
    # Espèces : 1000 - 101 x 0,92 = 907,08. Titres : 100 USD x 0,90 (marché) = 90.
    assert a["cash"].iloc[0] == pytest.approx(907.08)
    assert a["securities"].iloc[0] == pytest.approx(90)


def test_missing_fx_gives_nan_and_warning():
    hist = [tx("ACHAT", 0, acc=SECU, ticker="US1", q=2, p=50, cur="USD")]
    h = build_history(ACCOUNTS, hist, {"US1": prices(50, 60)}, {}, end=day(1))
    assert h.accounts[SECU.id]["value"].isna().all()
    assert any("USD/EUR indisponible" in w for w in h.warnings)
    assert pf.twr(h.total["value"], h.total["inflow"], h.total["outflow"]).total is None


def test_stale_prices_are_carried_then_missing():
    # Un seul cours au j0 : reporté 7 jours, puis valeur manquante (NaN, pas 0).
    hist = [tx("ACHAT", 0, acc=SECU, ticker="AAA", q=1, p=100)]
    h = build_history(ACCOUNTS, hist, {"AAA": prices(100)}, {}, end=day(10))
    v = h.accounts[SECU.id]["value"]
    assert v.iloc[:8].tolist() == [100.0] * 8
    assert v.iloc[8:].isna().all()
    assert h.stale["AAA"].iloc[1:8].all() and not h.stale["AAA"].iloc[0]
    assert any("Valorisation manquante pour AAA" in w for w in h.warnings)


def test_transaction_price_fills_missing_close():
    # Aucun cours fourni : le prix de la transaction sert de cours observé, marqué non frais.
    hist = [tx("ACHAT", 0, acc=SECU, ticker="NEW", q=4, p=25)]
    h = build_history(ACCOUNTS, hist, {}, {}, end=day(0))
    assert h.accounts[SECU.id]["value"].iloc[0] == pytest.approx(100)
    assert h.stale["NEW"].iloc[0]
    assert any("Aucun cours pour NEW" in w for w in h.warnings)


def test_closed_position_is_exactly_zero_without_price():
    hist = [tx("ACHAT", 0, acc=SECU, ticker="AAA", q=1, p=100),
            tx("VENTE", 1, acc=SECU, ticker="AAA", q=1, p=100)]
    h = build_history(ACCOUNTS, hist, {"AAA": prices(100, 100)}, {}, end=day(20))
    assert h.accounts[SECU.id]["value"].iloc[-1] == 0.0


def test_negative_cash_warns():
    hist = [tx("ACHAT", 0, ticker="AAA", q=1, p=100)]
    h = build_history(ACCOUNTS, hist, PX, {}, end=day(1))
    assert any("solde d'espèces négatif" in w for w in h.warnings)


def test_empty_history():
    h = build_history(ACCOUNTS, [], {}, {}, end=day(3))
    assert h.warnings == ["Aucune transaction."]
    assert (h.total["value"] == 0).all()


def test_holdings_eur_and_future_transactions_ignored():
    hist = [tx("ACHAT", 0, acc=SECU, ticker="AAA", q=2, p=100),
            tx("ACHAT", 9, acc=SECU, ticker="AAA", q=2, p=100)]       # après `end`
    h = build_history(ACCOUNTS, hist, PX, {}, end=day(4))
    assert h.holdings_eur[(SECU.id, "AAA")].iloc[-1] == pytest.approx(240)
    assert h.accounts[SECU.id]["inflow"].sum() == pytest.approx(200)
    assert not np.isnan(h.total["value"]).any()
