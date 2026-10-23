"""
Ajustement des transactions pour les divisions d'actions, sur des cas calculés à la main.

Cas de référence (NVDA, division par 10 avec effet au 10/06/2024) :
    10/01/2024  achat  3 à 900 $, 3 $ de frais      -> ajusté : 30 à 90 $
    01/03/2024  vente  1 à 1 000 $, 1 $ de frais    -> ajusté : 10 à 100 $
    10/06/2024  division 10 pour 1
    01/07/2024  achat  5 à 120 $, 1 $ de frais      -> non ajusté (après la division)
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from _factories import CASH, SECU, tx
from terminal import performance as pf
from terminal.errors import LedgerError
from terminal.ledger import Transaction, TxType, validate
from terminal.positions import compute_positions
from terminal.splits import Split, adjust_for_splits
from terminal.valuation import build_history

D = Decimal
SPLIT = Split("NVDA", date(2024, 6, 10), 10, 1)


def t(kind, d, q=None, p=None, fees="0", acc=CASH, amount=None, ticker="NVDA"):
    dec = lambda v: None if v is None else D(str(v))
    return Transaction(account_id=acc.id, date=d, type=TxType(kind), currency="USD", ticker=ticker,
                       quantity=dec(q), price=dec(p), amount=dec(amount), fees=D(fees), fx_rate=D("0.9"))


HISTORY = [t("ACHAT", date(2024, 1, 10), 3, 900, fees=3),
           t("VENTE", date(2024, 3, 1), 1, 1000, fees=1),
           t("ACHAT", date(2024, 7, 1), 5, 120, fees=1)]


def test_reference_case_adjusted_quantities_and_prices():
    adj, log = adjust_for_splits(HISTORY, {"NVDA": [SPLIT]})
    assert [(a.quantity, a.price) for a in adj] == [(D(30), D(90)), (D(10), D(100)), (D(5), D(120))]
    # Le montant brut saisi est conservé : 3 x 900 = 30 x 90 = 2 700.
    assert adj[0].gross == D(2700) and adj[1].gross == D(1000)
    assert [a.tx_date for a in log] == [date(2024, 1, 10), date(2024, 3, 1)]
    assert log[0].quantity_before == D(3) and log[0].quantity_after == D(30) and log[0].factor == 10
    # Les transactions d'origine ne sont pas modifiées.
    assert HISTORY[0].quantity == D(3) and HISTORY[0].price == D(900)


def test_reference_case_positions():
    adj, _ = adjust_for_splits(HISTORY, {"NVDA": [SPLIT]})
    pos = compute_positions(adj)[(CASH.id, "NVDA")]
    # Achat ajusté : 30 actions, coût 2 700 + 3 = 2 703, PRU = 90,10.
    # Vente ajustée de 10 à 100 : produit 1 000 - 1 = 999, coût sorti 10 x 90,10 = 901, PV = 98.
    # Achat de 5 à 120 + 1 : coût 601. Total : 25 actions, coût 1 802 + 601 = 2 403, PRU = 96,12.
    assert pos.quantity == D(25)
    assert pos.realized == D(98)
    assert pos.cost == D(2403)
    assert pos.pru == D("96.12")
    # Au cours de 130 $ : valeur 3 250, PV latente 3 250 - 2 403 = 847.
    assert pos.unrealized(D(130)) == D(847)


def test_without_adjustment_the_position_is_wrong():
    # Sans ajustement : 3 - 1 + 5 = 7 actions, valorisées au cours ajusté de 130 $ -> 910 $ au lieu de 3 250 $.
    pos = compute_positions(HISTORY)[(CASH.id, "NVDA")]
    assert pos.quantity == D(7) and pos.market_value(D(130)) == D(910)


def test_adjustment_leaves_pru_and_gains_unchanged_in_value():
    # Avant la division (historique arrêté au 01/03/2024), en unités d'origine :
    #   PRU = 2 703 / 3 = 901 $ ; PV réalisée = 999 - 901 = 98 $ ; coût restant 1 802 $ pour 2 actions.
    # Ajusté : PRU = 90,10 $ par action nouvelle, soit 901 $ pour l'équivalent d'une action
    # d'origine (10 actions nouvelles). PV réalisée et coût restant identiques.
    before = HISTORY[:2]
    raw = compute_positions(before)[(CASH.id, "NVDA")]
    adj = compute_positions(adjust_for_splits(before, {"NVDA": [SPLIT]})[0])[(CASH.id, "NVDA")]
    assert raw.pru == D(901) and adj.pru * 10 == raw.pru
    assert adj.realized == raw.realized == D(98)
    assert adj.cost == raw.cost == D(1802)
    assert adj.cost_eur == raw.cost_eur and adj.realized_eur == raw.realized_eur
    # Valeur au cours d'origine de 950 $ (= 95 $ ajusté) : 2 x 950 = 20 x 95 = 1 900.
    assert adj.market_value(D(95)) == raw.market_value(D(950)) == D(1900)
    assert adj.unrealized(D(95)) == raw.unrealized(D(950)) == D(98)


def test_transaction_on_split_date_is_not_adjusted():
    on_day = [t("ACHAT", date(2024, 6, 10), 10, 120)]
    adj, log = adjust_for_splits(on_day, {"NVDA": [SPLIT]})
    assert adj[0].quantity == D(10) and log == []


def test_successive_splits_cumulate():
    # NVDA : 4 pour 1 le 20/07/2021, puis 10 pour 1 le 10/06/2024. Un achat de 1 action en 2020 vaut 40 actions.
    splits = [Split("NVDA", date(2021, 7, 20), 4, 1), SPLIT]
    adj, log = adjust_for_splits([t("ACHAT", date(2020, 5, 4), 1, 400)], {"NVDA": splits})
    assert adj[0].quantity == D(40) and adj[0].price == D(10)
    assert log[0].factor == 40 and len(log[0].splits) == 2
    # Un achat entre les deux ne subit que la seconde.
    adj, _ = adjust_for_splits([t("ACHAT", date(2022, 1, 3), 2, 300)], {"NVDA": splits})
    assert adj[0].quantity == D(20) and adj[0].price == D(30)


def test_reverse_split_and_fractional_ratio():
    # Regroupement 1 pour 8 : 80 actions à 5 $ deviennent 10 actions à 40 $.
    rev = Split("XYZ", date(2024, 1, 1), 1, 8)
    adj, _ = adjust_for_splits([t("ACHAT", date(2023, 6, 1), 80, 5, ticker="XYZ")], {"XYZ": [rev]})
    assert adj[0].quantity == D(10) and adj[0].price == D(40)
    # Division 3 pour 2 : 2 actions à 150 $ deviennent 3 actions à 100 $.
    three_two = Split.from_ratio("ABC", date(2024, 1, 1), 1.5)
    assert (three_two.numerator, three_two.denominator) == (3, 2) and three_two.label == "3 pour 2"
    adj, _ = adjust_for_splits([t("ACHAT", date(2023, 6, 1), 2, 150, ticker="ABC")], {"ABC": [three_two]})
    assert adj[0].quantity == D(3) and adj[0].price == D(100)
    assert Split.from_ratio("R", date(2024, 1, 1), 0.125).denominator == 8


def test_invalid_split_and_untouched_types():
    with pytest.raises(ValueError):
        Split("X", date(2024, 1, 1), 0, 1)
    # Dividendes, dépôts, autres tickers : jamais ajustés.
    other = [tx("DIVIDENDE", 0, ticker="NVDA", amount=4, cur="USD"), tx("DEPOT", 0, amount=100),
             tx("ACHAT", 0, ticker="AAPL", q=1, p=10, cur="USD")]
    adj, log = adjust_for_splits(other, {"NVDA": [Split("NVDA", date(2030, 1, 1), 10, 1)]})
    assert adj == other and log == []


def test_validation_uses_adjusted_quantities():
    # 2 actions achetées avant la division, 20 vendues après : vente couverte une fois ajustée.
    hist = [t("ACHAT", date(2024, 1, 10), 2, 900), t("VENTE", date(2024, 8, 1), 20, 110)]
    with pytest.raises(LedgerError):
        validate([CASH, SECU], hist)
    adj, _ = adjust_for_splits(hist, {"NVDA": [SPLIT]})
    assert validate([CASH, SECU], adj) == []
    pos = compute_positions(adj)[(CASH.id, "NVDA")]
    assert pos.quantity == 0 and pos.realized == D(20 * 110 - 1800)


def test_valuation_through_split_is_continuous():
    # Clôtures ajustées (Yahoo) : 90 $ avant, 92 $ le jour de la division, 95 $ après.
    # 3 actions achetées à 900 $ (= 30 à 90 $) : la valeur ne saute pas le jour de la division.
    idx = pd.date_range("2024-06-08", periods=4, freq="D")
    closes = {"NVDA": pd.Series([90.0, 90.0, 92.0, 95.0], index=idx)}
    hist = [t("ACHAT", date(2024, 6, 8), 3, 900, acc=SECU)]
    adj, _ = adjust_for_splits(hist, {"NVDA": [SPLIT]})
    # Taux de marché égal au taux courtier (0,90) : la valeur en euros vaut 0,9 x la valeur en dollars.
    h = build_history([CASH, SECU], adj, closes, {"USD": pd.Series(0.9, index=idx)}, end=date(2024, 6, 11))
    assert h.accounts[SECU.id]["value"].tolist() == pytest.approx([2430, 2430, 2484, 2565])
    r = pf.twr(h.accounts[SECU.id]["value"], h.accounts[SECU.id]["inflow"], h.accounts[SECU.id]["outflow"])
    assert r.total == pytest.approx(95 / 90 - 1)
