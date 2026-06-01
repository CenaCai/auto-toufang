"""Pydantic schemas for API request/response."""

from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel


# --- Campaign ---
class CreativeCreate(BaseModel):
    name: str
    asset_url: str = ""
    sort_order: int = 0


class CampaignCreate(BaseModel):
    name: str
    platform: str  # "facebook" or "google"
    budget_cap: float
    cpi_cap: float
    roas_threshold: float | None = None
    creatives: list[CreativeCreate] = []


class CampaignUpdate(BaseModel):
    name: str | None = None
    budget_cap: float | None = None
    cpi_cap: float | None = None
    roas_threshold: float | None = None
    is_active: bool | None = None


class CreativeOut(BaseModel):
    id: int
    name: str
    asset_url: str
    sort_order: int
    is_active: bool

    model_config = {"from_attributes": True}


class CampaignOut(BaseModel):
    id: int
    name: str
    platform: str
    budget_cap: float
    cpi_cap: float
    roas_threshold: float | None
    current_creative_index: int
    is_active: bool
    created_at: datetime.datetime
    creatives: list[CreativeOut] = []

    model_config = {"from_attributes": True}


# --- Stats ---
class CampaignStats(BaseModel):
    """Stats returned by ads platform client."""
    campaign_id: int
    impressions: int = 0
    clicks: int = 0
    installs: int = 0
    spend: float = 0.0
    revenue: float = 0.0
    cpi: float = 0.0
    roas: float = 0.0


class PlatformSummary(BaseModel):
    platform: str
    total_spend: float
    avg_cpi: float
    overall_roas: float
    campaign_count: int
    is_healthy: bool


class OptimizationResult(BaseModel):
    timestamp: datetime.datetime
    daily_spend_total: float
    daily_cap: float
    fb_summary: PlatformSummary | None = None
    google_summary: PlatformSummary | None = None
    action: str  # "split_even", "shift_to_fb", "shift_to_google", "paused_all"
    budget_allocation: dict[str, float] = {}  # platform -> allocated budget


# --- Reports ---
class SpendRecordOut(BaseModel):
    id: int
    campaign_id: int
    platform: str
    hour: datetime.datetime
    impressions: int
    clicks: int
    installs: int
    spend: float
    revenue: float
    cpi: float
    roas: float

    model_config = {"from_attributes": True}


class ReportOut(BaseModel):
    id: int
    report_type: str
    period_start: datetime.datetime
    period_end: datetime.datetime
    payload: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class TodayStats(BaseModel):
    date: str
    total_spend: float
    daily_cap: float
    fb_spend: float
    google_spend: float
    fb_avg_cpi: float
    google_avg_cpi: float
    fb_roas: float
    google_roas: float
    active_campaigns: int
    total_installs: int
