"""
Positions calculées à partir des transactions.

Prix de revient : coût moyen pondéré, frais d'achat inclus (méthode du PMP,
celle de l'administration fiscale française). Une vente ne modifie pas le PRU.

    PRU            = coût des titres détenus / quantité détenue
    PV réalisée    = (brut de vente - frais de vente) - PRU x quantité vendue
    PV latente     = quantité x cours - coût des titres détenus

En euros, le coût historique utilise le taux du jour de chaque opération :
`fx_rate` du courtier s'il est fourni, sinon le taux de marché (`fx_at`).
Si aucun taux n'est disponible, les montants en euros valent None : une
donnée manquante n'est jamais remplacée par zéro.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .errors import MissingCurrency
from .ledger import ZERO, Transaction, TxType, ordered

# fx_at(devise, date) -> euros pour une unité de devise ; lève MissingCurrency.
FxLookup = Callable[[str, date], Decimal]


def _add(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a + b


def _mul(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a * b


def transaction_rate(tx: Transaction, fx_at: FxLookup | None) -> Decimal | None:
    """Taux EUR d'une opération : 1 en EUR, sinon taux du courtier, sinon marché."""
    if tx.currency == "EUR":
        return Decimal(1)
    if tx.fx_rate is not None:
        return tx.fx_rate
    if fx_at is None:
        return None
    try:
        return fx_at(tx.currency, tx.date)
    except MissingCurrency:
        return None


@dataclass
class Position:
    account_id: int
    ticker: str
    currency: str
    quantity: Decimal = ZERO
    cost: Decimal = ZERO                  # coût des titres détenus, frais inclus
    cost_eur: Decimal | None = ZERO
    realized: Decimal = ZERO              # PV réalisée cumulée, devise de cotation
    realized_eur: Decimal | None = ZERO
    dividends: Decimal = ZERO             # dividendes nets cumulés
    dividends_eur: Decimal | None = ZERO
    fees: Decimal = ZERO                  # frais de courtage cumulés
    first_date: date | None = None

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    @property
    def pru(self) -> Decimal | None:
        return self.cost / self.quantity if self.quantity > 0 else None

    @property
    def pru_eur(self) -> Decimal | None:
        if self.quantity <= 0 or self.cost_eur is None:
            return None
        return self.cost_eur / self.quantity

    def market_value(self, price: Decimal | None) -> Decimal | None:
        return None if price is None else self.quantity * price

    def unrealized(self, price: Decimal | None) -> Decimal | None:
        mv = self.market_value(price)
        return None if mv is None else mv - self.cost

    def market_value_eur(self, price: Decimal | None, fx: Decimal | None) -> Decimal | None:
        return _mul(self.market_value(price), fx)

    def unrealized_eur(self, price: Decimal | None, fx: Decimal | None) -> Decimal | None:
        mv = self.market_value_eur(price, fx)
        return None if mv is None or self.cost_eur is None else mv - self.cost_eur


def compute_positions(transactions: list[Transaction],
                      fx_at: FxLookup | None = None) -> dict[tuple[int, str], Position]:
    """
    Une position par couple (compte, ticker), positions soldées comprises
    (elles portent la PV réalisée). Les transactions doivent avoir été
    validées par `ledger.validate`.
    """
    out: dict[tuple[int, str], Position] = {}
    for tx in ordered(transactions):
        if tx.type not in (TxType.ACHAT, TxType.VENTE, TxType.DIVIDENDE):
            continue
        key = (tx.account_id, tx.ticker)
        pos = out.get(key)
        if pos is None:
            pos = out[key] = Position(tx.account_id, tx.ticker, tx.currency, first_date=tx.date)
        rate = transaction_rate(tx, fx_at)

        if tx.type is TxType.ACHAT:
            cost = tx.gross + tx.fees
            pos.quantity += tx.quantity
            pos.cost += cost
            pos.cost_eur = _add(pos.cost_eur, _mul(cost, rate))
            pos.fees += tx.fees

        elif tx.type is TxType.VENTE:
            share = tx.quantity / pos.quantity
            removed = pos.cost * share
            removed_eur = _mul(pos.cost_eur, share)
            proceeds = tx.gross - tx.fees
            proceeds_eur = _mul(proceeds, rate)
            pos.realized += proceeds - removed
            pos.realized_eur = _add(pos.realized_eur,
                                    None if proceeds_eur is None or removed_eur is None
                                    else proceeds_eur - removed_eur)
            pos.quantity -= tx.quantity
            pos.fees += tx.fees
            if pos.quantity == 0:
                # Position soldée : aucun résidu d'arrondi ne doit subsister.
                pos.cost = ZERO
                pos.cost_eur = ZERO if pos.cost_eur is not None else None
            else:
                pos.cost -= removed
                pos.cost_eur = None if removed_eur is None else pos.cost_eur - removed_eur

        else:  # DIVIDENDE
            pos.dividends += tx.gross
            pos.dividends_eur = _add(pos.dividends_eur, _mul(tx.gross, rate))
    return out
