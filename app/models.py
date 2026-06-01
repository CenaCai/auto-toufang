"""SQLAlchemy ORM models."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # "facebook" or "google"
    budget_cap: Mapped[float] = mapped_column(Float, nullable=False)
    cpi_cap: Mapped[float] = mapped_column(Float, nullable=False)
    roas_threshold: Mapped[float] = mapped_column(Float, nullable=True)
    current_creative_index: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    creatives: Mapped[list["Creative"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    spend_records: Mapped[list["SpendRecord"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class Creative(Base):
    __tablename__ = "creatives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_url: Mapped[str] = mapped_column(String(500), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="creatives")


class SpendRecord(Base):
    __tablename__ = "spend_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    hour: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    installs: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[float] = mapped_column(Float, default=0.0)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    cpi: Mapped[float] = mapped_column(Float, default=0.0)
    roas: Mapped[float] = mapped_column(Float, default=0.0)
    creative_id: Mapped[int | None] = mapped_column(
        ForeignKey("creatives.id"), nullable=True
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="spend_records")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "hourly" or "daily"
    period_start: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    period_end: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON blob
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
