"""
Grand livre : comptes et transactions.

Tous les montants sont des `Decimal`. Aucun flottant ici : les flottants sont
réservés aux calculs statistiques (valuation, performance, metrics).

Conventions
-----------
- Les quantités et prix des achats et ventes sont exprimés dans la devise de
  la cotation (le ticker). Les frais sont dans la même devise.
- `amount` d'un achat ou d'une vente est le montant brut hors frais, s'il est
  fourni ; sinon il vaut quantité x prix.
- `amount` d'un dividende est le montant net reçu (après retenue à la source).
- `fx_rate` est le taux appliqué par le courtier : nombre d'euros pour une
  unité de la devise de la transaction. Facultatif.
- Chaque compte a une convention de flux explicite (`CashMode`), jamais deux.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from .errors import LedgerError

ZERO = Decimal(0)

# Tolérance d'arrondi entre `amount` et quantité x prix (un centime).
AMOUNT_TOLERANCE = Decimal("0.01")

CURRENCIES = frozenset({
    "EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD", "SEK", "NOK", "DKK", "HKD",
})


class TxType(StrEnum):
    ACHAT = "ACHAT"
    VENTE = "VENTE"
    DIVIDENDE = "DIVIDENDE"
    DEPOT = "DEPOT"
    RETRAIT = "RETRAIT"
    FRAIS = "FRAIS"


TRADES = frozenset({TxType.ACHAT, TxType.VENTE})
NEEDS_TICKER = frozenset({TxType.ACHAT, TxType.VENTE, TxType.DIVIDENDE})
CASH_MOVES = frozenset({TxType.DEPOT, TxType.RETRAIT})

# Ordre des opérations d'une même journée : les apports avant les achats,
# les achats avant les ventes, les retraits en dernier.
_DAY_ORDER = {TxType.DEPOT: 0, TxType.ACHAT: 1, TxType.DIVIDENDE: 2,
              TxType.FRAIS: 3, TxType.VENTE: 4, TxType.RETRAIT: 5}


class CashMode(StrEnum):
    # Les espèces font partie du compte : seuls dépôts et retraits sont des flux externes.
    AVEC_ESPECES = "avec_especes"
    # Pas d'espèces suivies : chaque achat est un apport, chaque vente un retrait.
    TITRES_SEULS = "titres_seuls"


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    cash_mode: CashMode
    currency: str = "EUR"


@dataclass(frozen=True)
class Transaction:
    account_id: int
    date: date
    type: TxType
    currency: str
    ticker: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fees: Decimal = ZERO
    fx_rate: Decimal | None = None
    withholding: Decimal | None = None
    id: int | None = None          # ordre de saisie, départage une même journée

    @property
    def gross(self) -> Decimal:
        """Montant brut hors frais, dans la devise de la transaction."""
        if self.amount is not None:
            return self.amount
        if self.quantity is not None and self.price is not None:
            return self.quantity * self.price
        raise LedgerError([f"Transaction {self._label()} : montant indéterminé."])

    @property
    def net_cash(self) -> Decimal:
        """
        Variation d'espèces du compte, signée, dans la devise de la transaction.
        ACHAT : -(brut + frais) ; VENTE : brut - frais ; DIVIDENDE : +net ;
        DEPOT : +montant ; RETRAIT : -montant ; FRAIS : -montant.
        """
        g = self.gross
        return {
            TxType.ACHAT: -(g + self.fees),
            TxType.VENTE: g - self.fees,
            TxType.DIVIDENDE: g,
            TxType.DEPOT: g,
            TxType.RETRAIT: -g,
            TxType.FRAIS: -g,
        }[self.type]

    def _label(self) -> str:
        ref = f"#{self.id}" if self.id is not None else ""
        return f"{ref} {self.type} du {self.date.isoformat()}".strip()


@dataclass(frozen=True)
class Flows:
    """Flux externes d'une opération, positifs, dans la devise de la transaction."""
    inflow: Decimal = ZERO             # apport au compte
    outflow: Decimal = ZERO            # retrait du compte
    sleeve_inflow: Decimal = ZERO      # apport à la poche titres
    sleeve_outflow: Decimal = ZERO     # retrait de la poche titres


def external_flows(tx: Transaction, mode: CashMode) -> Flows:
    """
    Seule définition des flux externes, utilisée partout.

        convention      apports (inflow)              retraits (outflow)
        avec_especes    DEPOT                         RETRAIT
        titres_seuls    ACHAT (brut + frais), FRAIS   VENTE (brut - frais), DIVIDENDE

    La poche titres suit toujours la règle « titres seuls », hors FRAIS de
    compte : un compte avec espèces les paie sur ses espèces.
    """
    g, f = tx.gross, tx.fees
    s_in = g + f if tx.type is TxType.ACHAT else ZERO
    s_out = g - f if tx.type is TxType.VENTE else g if tx.type is TxType.DIVIDENDE else ZERO
    if mode is CashMode.AVEC_ESPECES:
        return Flows(inflow=g if tx.type is TxType.DEPOT else ZERO,
                     outflow=g if tx.type is TxType.RETRAIT else ZERO,
                     sleeve_inflow=s_in, sleeve_outflow=s_out)
    # Titres seuls : des frais payés de l'extérieur sont un apport aussitôt consommé.
    return Flows(inflow=s_in + (g if tx.type is TxType.FRAIS else ZERO), outflow=s_out,
                 sleeve_inflow=s_in, sleeve_outflow=s_out)


def sort_key(tx: Transaction) -> tuple:
    return (tx.date, _DAY_ORDER[tx.type], tx.id if tx.id is not None else 0)


def ordered(transactions: list[Transaction]) -> list[Transaction]:
    return sorted(transactions, key=sort_key)


def validate(accounts: list[Account], transactions: list[Transaction],
             listing_currency: dict[str, str] | None = None) -> list[str]:
    """
    Vérifie la cohérence de l'historique. Lève `LedgerError` avec la liste
    complète des erreurs ; renvoie la liste des avertissements sinon.
    """
    errors: list[str] = []
    warnings: list[str] = []
    by_id = {a.id: a for a in accounts}
    held: dict[tuple[int, str], Decimal] = {}
    ever_held: set[tuple[int, str]] = set()

    for a in accounts:
        if a.currency not in CURRENCIES:
            errors.append(f"Compte {a.name} : devise inconnue {a.currency}.")

    for tx in ordered(transactions):
        lbl = tx._label()
        acc = by_id.get(tx.account_id)
        if acc is None:
            errors.append(f"{lbl} : compte {tx.account_id} inexistant.")
            continue
        if tx.currency not in CURRENCIES:
            errors.append(f"{lbl} : devise inconnue {tx.currency}.")
        if tx.fees < 0:
            errors.append(f"{lbl} : frais négatifs.")
        if tx.fx_rate is not None:
            if tx.fx_rate <= 0:
                errors.append(f"{lbl} : taux de change non positif.")
            elif tx.currency == "EUR" and tx.fx_rate != 1:
                errors.append(f"{lbl} : taux de change différent de 1 pour une opération en EUR.")

        if tx.type in NEEDS_TICKER:
            if not tx.ticker:
                errors.append(f"{lbl} : ticker manquant.")
                continue
            if listing_currency is not None:
                cur = listing_currency.get(tx.ticker)
                if cur is None:
                    errors.append(f"{lbl} : ticker {tx.ticker} non référencé.")
                elif cur != tx.currency:
                    errors.append(f"{lbl} : devise {tx.currency} différente de celle "
                                  f"de la cotation {tx.ticker} ({cur}).")
        elif tx.ticker:
            errors.append(f"{lbl} : un {tx.type} ne porte pas de ticker.")

        if tx.type in TRADES:
            if tx.quantity is None or tx.quantity <= 0:
                errors.append(f"{lbl} : quantité manquante ou non positive.")
                continue
            if tx.price is None or tx.price <= 0:
                errors.append(f"{lbl} : prix manquant ou non positif.")
                continue
            if tx.amount is not None:
                if abs(tx.amount - tx.quantity * tx.price) > AMOUNT_TOLERANCE:
                    errors.append(f"{lbl} : montant {tx.amount} incohérent avec "
                                  f"quantité x prix = {tx.quantity * tx.price}.")
            key = (tx.account_id, tx.ticker)
            q = held.get(key, ZERO)
            if tx.type is TxType.ACHAT:
                held[key] = q + tx.quantity
                ever_held.add(key)
            else:
                if tx.quantity > q:
                    errors.append(f"{lbl} : vente de {tx.quantity} {tx.ticker}, "
                                  f"seulement {q} détenus.")
                    continue
                held[key] = q - tx.quantity
        else:
            if tx.amount is None or tx.amount <= 0:
                errors.append(f"{lbl} : montant manquant ou non positif.")
                continue

        if tx.type is TxType.DIVIDENDE:
            if tx.withholding is not None and tx.withholding < 0:
                errors.append(f"{lbl} : retenue à la source négative.")
            if (tx.account_id, tx.ticker) not in ever_held:
                warnings.append(f"{lbl} : dividende sur {tx.ticker}, jamais détenu dans ce compte.")

        if tx.type in CASH_MOVES and acc.cash_mode is CashMode.TITRES_SEULS:
            errors.append(f"{lbl} : le compte {acc.name} est en convention « titres seuls », "
                          f"il n'accepte ni dépôt ni retrait.")

    if errors:
        raise LedgerError(errors)
    return warnings
