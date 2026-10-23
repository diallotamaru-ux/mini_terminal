"""État de l'application et dépendances FastAPI."""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from fastapi import Request
from sqlalchemy.orm import Session

from terminal.marketdata.base import MarketDataProvider
from terminal.marketdata.rates import RateProvider

from .config import Settings
from .db import Database
from .services.portfolio import Snapshot, snapshot

SNAPSHOT_TTL_SECONDS = 300


@dataclass
class AppState:
    settings: Settings
    db: Database
    provider: MarketDataProvider
    rates: RateProvider
    revision: int = 0                                 # incrémenté à chaque écriture
    _memo: tuple | None = None
    _risk_memo: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def touch(self) -> None:
        self.revision += 1

    def risk(self, s: Session, period: str, reference: int, as_of: dt.date | None = None):
        """Page Risque, mise en cache comme l'instantané (même révision, même tranche de 5 minutes)."""
        from . import settings_store
        from .services.risk import risk_out

        snap = self.snapshot(s, as_of)
        key = (self.revision, snap.as_of, period, reference, int(time.time() // SNAPSHOT_TTL_SECONDS))
        with self._lock:
            hit = self._risk_memo.get(key)
        if hit is not None:
            return hit
        out = risk_out(snap, self.provider, self.rates, settings_store.load(s), period, reference)
        with self._lock:
            self._risk_memo = {**self._risk_memo, key: out} if len(self._risk_memo) < 20 else {key: out}
        return out

    def snapshot(self, s: Session, as_of: dt.date | None = None) -> Snapshot:
        """Un calcul complet par révision du grand livre, date et tranche de 5 minutes."""
        as_of = as_of or dt.date.today()
        key = (self.revision, as_of, int(time.time() // SNAPSHOT_TTL_SECONDS))
        with self._lock:
            if self._memo and self._memo[0] == key:
                return self._memo[1]
            snap = snapshot(s, self.provider, as_of)
            self._memo = (key, snap)
            return snap


def get_state(request: Request) -> AppState:
    return request.app.state.mt


def get_session(request: Request) -> Iterator[Session]:
    yield from request.app.state.mt.db.session()
