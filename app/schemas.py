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
    external_id: str = ""  # FB/Google campaign ID for linking to platform UI
    budget_cap: float
    cpi_cap: float
    roas_threshold: float | None = None
    creatives: list[CreativeCreate] = []


class CampaignUpdate(BaseModel):
    name: str | None = None
    external_id: str | None = None
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
    external_id: str
    budget_cap: float
    cpi_cap: float
    roas_threshold: float | None
    current_creative_index: int
    is_active: bool
    created_at: datetime.datetime
    creatives: list[CreativeOut] = []
    platform_url: str = ""  # computed: link to FB/Google Ads manager

    model_config = {"from_attributes": True}

    def model_post_init(self, __context):
        if self.external_id:
            if self.platform == "facebook":
                self.platform_url = f"https://business.facebook.com/adsmanager/manage/campaigns?act=&selected_campaign_ids={self.external_id}"
            elif self.platform == "google":
                self.platform_url = f"https://ads.google.com/aw/campaigns?campaignId={self.external_id}"
            elif self.platform == "tiktok":
                self.platform_url = f"https://ads.tiktok.com/i18n/perf?aadvid={self.external_id}"


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
    platform_summaries: dict[str, PlatformSummary] = {}  # platform_name -> summary
    action: str  # "split_even", "shift_to_<platform>", "paused_all"
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


class PlatformStats(BaseModel):
    spend: float = 0.0
    avg_cpi: float = 0.0
    roas: float = 0.0
    installs: int = 0


class TodayStats(BaseModel):
    date: str
    total_spend: float
    daily_cap: float
    platforms: dict[str, PlatformStats] = {}  # platform_name -> stats
    active_campaigns: int
    total_installs: int
