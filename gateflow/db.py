from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .config import get_settings

logger = logging.getLogger("gateflow.db")


class Base(DeclarativeBase):
    pass


class APIKeyRecordDB(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    tier: Mapped[str] = mapped_column(String(64))
    active: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rate_limit_custom: Mapped[int] = mapped_column(Integer, default=-1)
    rate_limit_custom_refill: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_count_lifetime: Mapped[int] = mapped_column(BigInteger, default=0)
    allowed_ips: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TierRequestDB(Base):
    __tablename__ = "tier_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    current_tier: Mapped[str] = mapped_column(String(64))
    requested_tier: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditEventDB(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    resource: Mapped[str] = mapped_column(String(255), index=True)
    admin_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RouteDB(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prefix: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    target_url: Mapped[str] = mapped_column(String(512))
    fallback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    strip_prefix: Mapped[bool] = mapped_column(default=True)
    requires_auth: Mapped[bool] = mapped_column(default=True)
    allowed_methods: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageDailyDB(Base):
    __tablename__ = "usage_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    route: Mapped[str] = mapped_column(String(255), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    requests: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_in: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_out: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "route", "day", name="uix_usage_daily_user_route_day"),
        {"sqlite_autoincrement": True},
    )


class TierConfigDB(Base):
    __tablename__ = "tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    capacity: Mapped[int] = mapped_column(Integer)
    refill_rate: Mapped[float] = mapped_column()
    window_info: Mapped[str] = mapped_column(String(32), default="1s")
    monthly_quota: Mapped[int] = mapped_column(Integer, default=-1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


_engine = None
_session_maker = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        kwargs: dict[str, Any] = {"echo": settings.debug, "future": True}
        if url.startswith("sqlite"):
            # SQLite can serialize on a single connection. Use a long busy
            # timeout and, for file-backed databases, avoid extra connections.
            kwargs["connect_args"] = {"timeout": 60.0}
            if ":memory:" not in url:
                kwargs["pool_size"] = 1
                kwargs["max_overflow"] = 0
        _engine = create_async_engine(url, **kwargs)
    return _engine


def _get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(_get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _session_maker


async def init_db() -> None:
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_maker = None


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with _get_session_maker()() as session:
        try:
            yield session
        finally:
            await session.close()


async def new_db_session() -> AsyncSession:
    """Return a standalone session (use with a context manager or manual close)."""
    return _get_session_maker()()
