"""Validation du grand livre : chaque incohérence doit être refusée explicitement."""

from decimal import Decimal

import pytest

from _factories import CASH, SECU, day, tx
from terminal.errors import LedgerError
from terminal.ledger import Account, CashMode, Transaction, TxType, ordered, validate

ACCOUNTS = [CASH, SECU]


def errors_of(txs, **kw):
    with pytest.raises(LedgerError) as e:
        validate(ACCOUNTS, txs, **kw)
    return e.value.errors


def test_valid_history_passes():
    txs = [tx("DEPOT", 0, amount=1000), tx("ACHAT", 0, ticker="AAA", q=5, p=100, fees=1),
           tx("DIVIDENDE", 3, ticker="AAA", amount=4, wh=1), tx("VENTE", 5, ticker="AAA", q=5, p=110),
           tx("RETRAIT", 6, amount=500), tx("FRAIS", 6, amount=2)]
    assert validate(ACCOUNTS, txs) == []


@pytest.mark.parametrize("kind,extra", [("DEPOT", {}), ("RETRAIT", {}), ("FRAIS", {}),
                                        ("DIVIDENDE", {"ticker": "AAA"})])
def test_fees_outside_buy_and_sell_are_refused(kind, extra):
    """Revue : un DEPOT de 100 avec 5 de frais passait la validation, et les frais disparaissaient du solde."""
    txs = [tx("DEPOT", 0, amount=1000), tx("ACHAT", 0, ticker="AAA", q=1, p=100), tx(kind, 1, amount=100, fees=5, **extra)]
    errs = errors_of(txs)
    assert len(errs) == 1 and f"frais saisis sur un {kind}" in errs[0]


def test_deposit_refused_in_securities_only_account():
    errs = errors_of([tx("DEPOT", 0, acc=SECU, amount=1000)])
    assert "titres seuls" in errs[0]


def test_withdrawal_refused_in_securities_only_account():
    errs = errors_of([tx("RETRAIT", 0, acc=SECU, amount=10)])
    assert "titres seuls" in errs[0]


def test_oversell_refused():
    errs = errors_of([tx("ACHAT", 0, ticker="AAA", q=2, p=10), tx("VENTE", 1, ticker="AAA", q=3, p=10)])
    assert "seulement 2 détenus" in errs[0]


def test_sale_in_other_account_is_oversell():
    errs = errors_of([tx("ACHAT", 0, ticker="AAA", q=2, p=10),
                      tx("VENTE", 1, acc=SECU, ticker="AAA", q=1, p=10)])
    assert "seulement 0 détenus" in errs[0]


def test_same_day_buy_then_sell_is_allowed():
    # Saisis dans l'ordre inverse : l'achat passe avant la vente du même jour.
    sell = tx("VENTE", 0, ticker="AAA", q=1, p=10)
    buy = tx("ACHAT", 0, ticker="AAA", q=1, p=10)
    assert validate(ACCOUNTS, [sell, buy]) == []
    assert ordered([sell, buy])[0] is buy


def test_all_errors_are_reported_at_once():
    errs = errors_of([
        tx("ACHAT", 0, ticker="AAA", q=1, p=10, cur="XYZ"),        # devise inconnue
        tx("ACHAT", 0, q=1, p=10),                                 # ticker manquant
        tx("DEPOT", 0, ticker="AAA", amount=10),                   # ticker sur un dépôt
        tx("ACHAT", 0, ticker="AAA", q=0, p=10),                   # quantité nulle
        tx("ACHAT", 0, ticker="AAA", q=1, p=-1),                   # prix négatif
        tx("ACHAT", 0, ticker="AAA", q=2, p=10, amount=25),        # montant incohérent
        tx("DEPOT", 0, amount=0),                                  # montant nul
        tx("ACHAT", 0, ticker="AAA", q=1, p=10, fees="-1"),        # frais négatifs
        tx("ACHAT", 0, ticker="BBB", q=1, p=10, cur="USD", fx="0"),  # taux nul
        tx("ACHAT", 0, ticker="AAA", q=1, p=10, fx="0.9"),         # taux != 1 en EUR
        tx("DIVIDENDE", 0, ticker="AAA", amount=1, wh="-1"),       # retenue négative
    ])
    assert len(errs) == 11


def test_amount_within_one_cent_is_accepted():
    # 0,123456 x 512,34 = 63,2516... : le courtier débite 63,25.
    assert validate(ACCOUNTS, [tx("ACHAT", 0, ticker="AAA", q="0.123456", p="512.34",
                                  amount="63.25")]) == []


def test_listing_currency_is_enforced():
    errs = errors_of([tx("ACHAT", 0, ticker="AAA", q=1, p=10, cur="USD"),
                      tx("ACHAT", 0, ticker="ZZZ", q=1, p=10)],
                     listing_currency={"AAA": "EUR"})
    assert "différente de celle de la cotation" in errs[0]
    assert "non référencé" in errs[1]


def test_unknown_account_and_account_currency():
    accounts = [Account(9, "Exotique", CashMode.AVEC_ESPECES, currency="XYZ")]
    t = Transaction(account_id=42, date=day(0), type=TxType.DEPOT, currency="EUR",
                    amount=Decimal(1))
    with pytest.raises(LedgerError) as e:
        validate(accounts, [t])
    assert len(e.value.errors) == 2


def test_dividend_on_never_held_ticker_warns():
    w = validate(ACCOUNTS, [tx("DIVIDENDE", 0, ticker="AAA", amount=3)])
    assert "jamais détenu" in w[0]


def test_gross_requires_amount_or_quantity_price():
    t = Transaction(account_id=1, date=day(0), type=TxType.ACHAT, currency="EUR", ticker="AAA")
    with pytest.raises(LedgerError):
        _ = t.gross
    assert tx("ACHAT", ticker="AAA", q=2, p=3).gross == Decimal(6)
    assert tx("ACHAT", ticker="AAA", q=2, p=3, fees=1).net_cash == Decimal(-7)
    assert tx("VENTE", ticker="AAA", q=2, p=3, fees=1).net_cash == Decimal(5)
