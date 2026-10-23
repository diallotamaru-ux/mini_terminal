"""
Divisions d'actions (et regroupements).

Les cours du fournisseur sont ajustés des divisions ; les transactions sont
saisies en quantités et prix d'origine. Pour les rendre comparables, chaque
achat ou vente antérieur à une division est ajusté AU CALCUL, sans toucher
aux données saisies :

    q' = q x n / d        p' = p x d / n        montant brut inchangé

avec n / d le nombre d'actions nouvelles pour une ancienne (10 / 1 pour une
division par 10, 1 / 8 pour un regroupement de 8 en 1). La valeur q x p, le
coût total, les frais et les plus-values en euros sont donc inchangés ; seul
le PRU par action est exprimé dans la nouvelle unité.

Une transaction est ajustée si sa date est strictement antérieure à la date
d'effet de la division (ex-date) : un ordre du jour même est déjà exécuté en
actions nouvelles. Plusieurs divisions successives se cumulent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

from .ledger import TRADES, Transaction


@dataclass(frozen=True)
class Split:
    ticker: str
    date: date               # date d'effet (ex-date)
    numerator: int           # actions nouvelles...
    denominator: int         # ... pour `denominator` anciennes

    def __post_init__(self):
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError(f"Division invalide pour {self.ticker} : {self.numerator}/{self.denominator}")

    @classmethod
    def from_ratio(cls, ticker: str, d: date, ratio: float) -> Split:
        """Ratio flottant du fournisseur (10.0, 0.125...) vers une fraction exacte."""
        f = Fraction(ratio).limit_denominator(1000)
        return cls(ticker, d, f.numerator, f.denominator)

    @property
    def label(self) -> str:
        return f"{self.numerator} pour {self.denominator}"


@dataclass(frozen=True)
class Adjustment:
    """Trace d'un ajustement, affichée à l'utilisateur."""
    tx_id: int | None
    account_id: int
    ticker: str
    tx_date: date
    tx_type: str
    splits: tuple[Split, ...]
    quantity_before: Decimal
    quantity_after: Decimal
    price_before: Decimal
    price_after: Decimal

    @property
    def factor(self) -> Fraction:
        f = Fraction(1)
        for s in self.splits:
            f *= Fraction(s.numerator, s.denominator)
        return f


def adjust_for_splits(transactions: list[Transaction],
                      splits: dict[str, list[Split]]) -> tuple[list[Transaction], list[Adjustment]]:
    """Renvoie les transactions ajustées (même ordre) et la liste des ajustements appliqués."""
    out: list[Transaction] = []
    adjustments: list[Adjustment] = []
    for tx in transactions:
        later = tuple(sorted((s for s in splits.get(tx.ticker or "", ()) if tx.date < s.date),
                             key=lambda s: s.date))
        if tx.type not in TRADES or not later:
            out.append(tx)
            continue
        num = den = 1
        for s in later:
            num *= s.numerator
            den *= s.denominator
        q = tx.quantity * num / den
        p = tx.price * den / num
        # Le montant brut saisi (ou q x p d'origine) est conservé : le coût reste exact au centime.
        adjusted = replace(tx, quantity=q, price=p, amount=tx.gross)
        out.append(adjusted)
        adjustments.append(Adjustment(tx.id, tx.account_id, tx.ticker, tx.date, tx.type.value, later,
                                      tx.quantity, q, tx.price, p))
    return out, adjustments
