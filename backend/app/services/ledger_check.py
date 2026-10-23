"""Validation d'une modification du grand livre avant écriture en base."""

from __future__ import annotations

from sqlalchemy.orm import Session

from terminal import ledger
from terminal.marketdata.base import MarketDataProvider
from terminal.splits import adjust_for_splits

from .portfolio import load_ledger, load_splits


def check(s: Session, provider: MarketDataProvider, add: list[ledger.Transaction] = (),
          remove_ids: set[int] = frozenset(),
          accounts: list[ledger.Account] | None = None,
          listing_currency: dict[str, str] | None = None) -> list[str]:
    """
    Valide l'historique complet tel qu'il serait après la modification, en
    quantités ajustées des divisions (une vente de 20 NVDA après la division
    par 10 est couverte par 2 actions achetées avant). Lève LedgerError ;
    renvoie les avertissements sinon.
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
    splits, warnings = load_splits(provider, (t.ticker for t in txs if t.ticker))
    txs, _ = adjust_for_splits(txs, splits)
    return warnings + ledger.validate(core_accounts, txs, cur)
