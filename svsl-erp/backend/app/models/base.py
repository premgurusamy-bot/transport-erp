"""Declarative base and the `F()` column helper.

`F()` stores UI/validation metadata (label, required, options, reference) in
`Column.info`, so the generic CRUD API and the React forms are generated from a
single definition.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


Money = Numeric(14, 2)
Qty = Numeric(14, 3)
Rate = Numeric(14, 4)


def F(
    type_: Any,
    label: str | None = None,
    *,
    required: bool = False,
    fk: str | None = None,
    ref: str | None = None,
    options: list[str] | None = None,
    secret: bool = False,
    hidden: bool = False,
    readonly: bool = False,
    help: str | None = None,
    validator: str | None = None,
    group: str | None = None,
    **kw: Any,
) -> Column:
    info = {
        "label": label,
        "required": required,
        "ref": ref,
        "options": options,
        "secret": secret,
        "hidden": hidden,
        "readonly": readonly,
        "help": help,
        "validator": validator,
        "group": group,
    }
    nullable = kw.pop("nullable", not required)
    args = [type_]
    if fk:
        ondelete = kw.pop("ondelete", None)
        args.append(ForeignKey(fk, ondelete=ondelete))
    return Column(*args, nullable=nullable, info=info, **kw)


class AuditMixin:
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, info={"readonly": True, "hidden": True})
    updated_at = Column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False, info={"readonly": True, "hidden": True}
    )
    created_by = Column(Integer, nullable=True, info={"readonly": True, "hidden": True})
    updated_by = Column(Integer, nullable=True, info={"readonly": True, "hidden": True})


class ActiveMixin:
    is_active = Column(Boolean, default=True, nullable=False, info={"label": "Active"})


__all__ = [
    "Base",
    "F",
    "AuditMixin",
    "ActiveMixin",
    "Money",
    "Qty",
    "Rate",
    "utcnow",
    "Column",
    "String",
    "Integer",
    "Date",
    "DateTime",
    "Boolean",
    "Numeric",
    "Text",
    "JSON",
    "ForeignKey",
]
