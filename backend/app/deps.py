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

from .config import Settings
from .db import Database
from .services.portfolio import Snapshot, snapshot

SNAPSHOT_TTL_SECONDS = 300


@dataclass
class AppState:
    settings: Settings
    db: Database
    provider: MarketDataProvider
    revision: int = 0                                 # incrémenté à chaque écriture
    _memo: tuple | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def touch(self) -> None:
        self.revision += 1

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
