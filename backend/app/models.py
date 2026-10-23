"""
Tables. Tous les montants sont en `DecimalText`.

Instrument (le titre, identifié par son ISIN quand il en a un) et Listing (la
cotation : ticker, place, devise) sont distincts : un même ISIN peut coter
sur plusieurs places, dans plusieurs devises.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from terminal.ledger import CashMode, TxType

from .db import Base, DecimalText


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


ACCOUNT_KINDS = ("CTO", "PEA", "CRYPTO", "AUTRE")
ASSET_CLASSES = ("action", "etf", "crypto", "autre")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(f"kind IN {ACCOUNT_KINDS}", name="ck_account_kind"),
        CheckConstraint(f"cash_mode IN {tuple(m.value for m in CashMode)}", name="ck_cash_mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    broker: Mapped[str | None] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))
    cash_mode: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    asset_class: Mapped[str] = mapped_column(String(10), default="autre")

    listings: Mapped[list[Listing]] = relationship(back_populates="instrument")


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    exchange: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3))

    instrument: Mapped[Instrument] = relationship(back_populates="listings", lazy="joined")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(f"type IN {tuple(t.value for t in TxType)}", name="ck_tx_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[Decimal | None] = mapped_column(DecimalText)
    price: Mapped[Decimal | None] = mapped_column(DecimalText)
    amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    fees: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3))
    fx_rate: Mapped[Decimal | None] = mapped_column(DecimalText)
    withholding: Mapped[Decimal | None] = mapped_column(DecimalText)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    account: Mapped[Account] = relationship(back_populates="transactions")
    listing: Mapped[Listing | None] = relationship(lazy="joined")


class MarketBar(Base):
    """Cache des cours, taux et dividendes. `symbol` : ticker, « FX:USD », « DIV:QQQ », « RATE:ESTR »."""

    __tablename__ = "market_bars"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(DecimalText)


class MarketSplit(Base):
    """Cache des divisions d'actions (la plage associée est « SPLITS:<ticker> » dans MarketRange)."""

    __tablename__ = "market_splits"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    numerator: Mapped[int]
    denominator: Mapped[int]


class MarketRange(Base):
    """Plage déjà téléchargée pour un symbole, avec sa source."""

    __tablename__ = "market_ranges"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    start: Mapped[dt.date] = mapped_column(Date)
    end: Mapped[dt.date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(20))
    simulated: Mapped[bool] = mapped_column(default=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
