"""Validation d'une modification du grand livre avant écriture en base."""

from __future__ import annotations

from sqlalchemy.orm import Session

from terminal import ledger

from .portfolio import load_ledger


def check(s: Session, add: list[ledger.Transaction] = (), remove_ids: set[int] = frozenset(),
          accounts: list[ledger.Account] | None = None,
          listing_currency: dict[str, str] | None = None) -> list[str]:
    """
    Valide l'historique complet tel qu'il serait après la modification.
    Lève LedgerError ; renvoie les avertissements sinon.
    """
    _, core_accounts, txs, listings = load_ledger(s)
    cur = {t: l.currency for t, l in listings.items()}
    if listing_currency:
        cur.update(listing_currency)
    if accounts is not None:
        by_id = {a.id: a for a in core_accounts}
        by_id.update({a.id: a for a in accounts})
        core_accounts = list(by_id.values())
    txs = [t for t in txs if t.id not in remove_ids] + list(add)
    return ledger.validate(core_accounts, txs, cur)
