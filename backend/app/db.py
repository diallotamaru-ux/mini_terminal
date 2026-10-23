"""
Moteur SQLAlchemy 2 et type `DecimalText`.

SQLite n'a pas de type décimal : `Numeric` y stocke des flottants binaires
(0,1 devient 0,1000000000000000055...). `DecimalText` stocke le texte exact
du Decimal et le relit à l'identique.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

from sqlalchemy import String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class DecimalText(TypeDecorator):
    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(f"DecimalText attend un Decimal, reçu {type(value).__name__}")
        if not value.is_finite():
            raise ValueError("DecimalText refuse NaN et l'infini")
        return format(value, "f")

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kw = {"connect_args": {"check_same_thread": False}}
    if url == "sqlite://":
        kw["poolclass"] = StaticPool          # base en mémoire partagée (tests)
    engine = create_engine(url, **kw)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if url != "sqlite://":
            # WAL : une lecture en cours ne bloque pas l'écriture du cache des cours.
            cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.sessionmaker = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        from . import models  # noqa: F401 - enregistre les tables
        Base.metadata.create_all(self.engine)

    def session(self) -> Iterator[Session]:
        with self.sessionmaker() as s:
            yield s
