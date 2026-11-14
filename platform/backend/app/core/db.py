"""Database engine, declarative base and shared column types.

Rules: money is Numeric(14,2) (never float); timestamps are timezone-aware UTC;
primary keys are UUIDs plus human-readable codes where users need them.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from sqlalchemy import DateTime, MetaData, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


TWO = Decimal("0.01")


def money(v) -> Decimal:
    """Normalise any numeric input to a 2-dp Decimal (half-up, Indian accounting convention)."""
    if v is None:
        return Decimal("0.00")
    if isinstance(v, float):
        v = repr(v)
    return Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)


Money = Annotated[Decimal, mapped_column(Numeric(14, 2), default=Decimal("0.00"))]
Qty = Annotated[Decimal, mapped_column(Numeric(14, 3), default=Decimal("0"))]
Code = Annotated[str, mapped_column(String(40))]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=True)
    return _engine


def SessionLocal():
    get_engine()
    return _SessionLocal()


def reset_engine(url: str | None = None):
    """Used by tests to point the app at a different database."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url or get_settings().database_url, pool_pre_ping=True, future=True)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=True)
    return _engine
