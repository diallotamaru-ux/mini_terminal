"""Prix de revient moyen pondéré et plus-values, calculés à la main."""

from decimal import Decimal

import pytest

from _factories import CASH, day, tx
from terminal.errors import MissingCurrency
from terminal.positions import compute_positions

D = Decimal


def test_weighted_average_cost_hand_example():
    # Achat 10 à 100 + 5 de frais : coût 1 005.
    # Achat 10 à 120, sans frais  : coût 1 200.  PRU = 2 205 / 20 = 110,25.
    # Vente 5 à 130, 2 de frais   : produit 648 ; coût sorti 5 x 110,25 = 551,25.
    # PV réalisée = 648 - 551,25 = 96,75. Le PRU reste 110,25.
    txs = [tx("ACHAT", 0, ticker="AAA", q=10, p=100, fees=5),
           tx("ACHAT", 1, ticker="AAA", q=10, p=120),
           tx("VENTE", 2, ticker="AAA", q=5, p=130, fees=2)]
    pos = compute_positions(txs)[(CASH.id, "AAA")]
    assert pos.quantity == D(15)
    assert pos.pru == D("110.25")
    assert pos.realized == D("96.75")
    assert pos.cost == D("1653.75")
    assert pos.fees == D(7)
    # En EUR, tout est en EUR : identique.
    assert pos.pru_eur == D("110.25") and pos.realized_eur == D("96.75")
    # PV latente au cours de 140 : 15 x 140 - 1 653,75 = 446,25.
    assert pos.unrealized(D(140)) == D("446.25")
    assert pos.unrealized_eur(D(140), D(1)) == D("446.25")


def test_closed_position_has_no_residual_cost():
    txs = [tx("ACHAT", 0, ticker="AAA", q=3, p="33.33", fees="0.99"),
           tx("VENTE", 1, ticker="AAA", q=1, p=40), tx("VENTE", 2, ticker="AAA", q=2, p=40)]
    pos = compute_positions(txs)[(CASH.id, "AAA")]
    assert not pos.is_open
    assert pos.cost == 0 and pos.cost_eur == 0 and pos.pru is None and pos.pru_eur is None
    # 120 - (99,99 + 0,99) = 19,02
    assert pos.realized == D("19.02")


def test_usd_position_in_eur_uses_broker_rate_then_market_rate():
    # Achat 10 à 50 USD, taux courtier 0,90 : coût 500 USD = 450 EUR.
    # Vente 5 à 60 USD, sans taux courtier, marché 0,95 : produit 300 USD = 285 EUR.
    # Coût sorti en EUR : 450 / 2 = 225. PV réalisée EUR = 285 - 225 = 60.
    # PV réalisée USD = 300 - 250 = 50.
    txs = [tx("ACHAT", 0, ticker="US1", q=10, p=50, cur="USD", fx="0.90"),
           tx("VENTE", 5, ticker="US1", q=5, p=60, cur="USD")]
    fx_at = lambda cur, d: D("0.95")
    pos = compute_positions(txs, fx_at)[(CASH.id, "US1")]
    assert pos.cost_eur == D(225) and pos.realized == D(50) and pos.realized_eur == D(60)
    # Valeur au cours de 70 USD, taux du jour 1,00 : 350 EUR ; PV latente 350 - 225 = 125.
    assert pos.market_value_eur(D(70), D(1)) == D(350)
    assert pos.unrealized_eur(D(70), D(1)) == D(125)


def test_missing_fx_gives_none_not_zero():
    def fx_at(cur, d):
        raise MissingCurrency(cur)
    txs = [tx("ACHAT", 0, ticker="US1", q=10, p=50, cur="USD"),
           tx("DIVIDENDE", 1, ticker="US1", amount=3, cur="USD"),
           tx("VENTE", 2, ticker="US1", q=4, p=55, cur="USD")]
    pos = compute_positions(txs, fx_at)[(CASH.id, "US1")]
    assert pos.cost_eur is None and pos.realized_eur is None and pos.dividends_eur is None
    assert pos.realized == D(20)                      # en devise d'origine, tout reste connu
    assert compute_positions(txs[:1])[(CASH.id, "US1")].cost_eur is None   # aucun fx_at
    assert pos.unrealized(None) is None and pos.market_value_eur(D(1), None) is None


def test_fully_closed_with_missing_fx_keeps_none():
    txs = [tx("ACHAT", 0, ticker="US1", q=1, p=50, cur="USD"),
           tx("VENTE", 1, ticker="US1", q=1, p=55, cur="USD")]
    pos = compute_positions(txs)[(CASH.id, "US1")]
    assert pos.cost_eur is None and pos.cost == 0


def test_dividends_and_ignored_cash_moves():
    txs = [tx("DEPOT", 0, amount=1000), tx("ACHAT", 0, ticker="AAA", q=1, p=10),
           tx("DIVIDENDE", 30, ticker="AAA", amount="0.42"), tx("FRAIS", 31, amount=1)]
    out = compute_positions(txs)
    assert list(out) == [(CASH.id, "AAA")]
    assert out[(CASH.id, "AAA")].dividends == D("0.42")
    assert out[(CASH.id, "AAA")].first_date == day(0)


@pytest.mark.parametrize("q,p", [("0.0001", "65000"), ("123.456789", "0.0123")])
def test_decimal_precision_on_fractional_quantities(q, p):
    txs = [tx("ACHAT", 0, ticker="BTC-EUR", q=q, p=p), tx("VENTE", 1, ticker="BTC-EUR", q=q, p=p)]
    pos = compute_positions(txs)[(CASH.id, "BTC-EUR")]
    assert pos.realized == 0 and pos.quantity == 0


def test_cash_balances_in_decimal():
    from _factories import SECU
    from terminal.positions import cash_balances
    # 1 000 - (10 x 50 + 1) + 3,10 - 2 = 500,10
    txs = [tx("DEPOT", 0, amount=1000), tx("ACHAT", 0, ticker="AAA", q=10, p=50, fees=1),
           tx("DIVIDENDE", 1, ticker="AAA", amount="3.10"), tx("FRAIS", 2, amount=2),
           tx("ACHAT", 0, acc=SECU, ticker="AAA", q=1, p=1)]
    out = cash_balances([CASH, SECU], txs)
    assert out == {CASH.id: D("500.10")}
    # Achat en USD au taux courtier 0,9 : 100 USD -> 90 EUR débités.
    usd = txs + [tx("ACHAT", 3, ticker="US1", q=1, p=100, cur="USD", fx="0.9")]
    assert cash_balances([CASH], usd)[CASH.id] == D("410.10")
    # Sans taux : solde inconnu.
    assert cash_balances([CASH], txs + [tx("ACHAT", 3, ticker="US1", q=1, p=100, cur="USD")])[CASH.id] is None
