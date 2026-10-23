"""Constructeurs concis pour les tests du grand livre."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from itertools import count

import pandas as pd

from terminal.ledger import Account, CashMode, Transaction, TxType

D0 = date(2024, 1, 1)
_ids = count(1)

CASH = Account(1, "CTO", CashMode.AVEC_ESPECES)
SECU = Account(2, "PEA", CashMode.TITRES_SEULS)


def day(n: int) -> date:
    return D0 + timedelta(days=n)


def tx(kind: str, n: int = 0, *, acc: Account = CASH, ticker: str | None = None,
       q=None, p=None, amount=None, fees="0", cur: str = "EUR", fx=None, wh=None) -> Transaction:
    dec = lambda v: None if v is None else Decimal(str(v))
    return Transaction(account_id=acc.id, date=day(n), type=TxType(kind), currency=cur,
                       ticker=ticker, quantity=dec(q), price=dec(p), amount=dec(amount),
                       fees=Decimal(fees), fx_rate=dec(fx), withholding=dec(wh), id=next(_ids))


def prices(*values: float, start: int = 0) -> pd.Series:
    """Série de clôtures quotidiennes à partir de day(start)."""
    idx = pd.date_range(day(start), periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)
