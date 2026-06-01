"""Mock Google Ads client for development/testing."""

from __future__ import annotations

import random
from datetime import date

from app.schemas import CampaignStats
from app.services.ads_interface import AdsClient


class MockGoogleClient(AdsClient):
    """Simulates Google Ads API responses.

    Google Ads mock tends to have slightly lower CPI but more variable ROAS
    compared to the Facebook mock, reflecting typical real-world patterns.
    """

    platform = "google"

    def __init__(self, seed: int | None = None):
        if seed is not None:
            random.seed(seed)
        self._budgets: dict[int, float] = {}
        self._active_creatives: dict[int, int] = {}
        self._paused: set[int] = set()

    async def get_campaign_stats(
        self, campaign_id: int, hour: date | None = None
    ) -> CampaignStats:
        if campaign_id in self._paused:
            return CampaignStats(campaign_id=campaign_id)

        budget = self._budgets.get(campaign_id, 500.0)
        hourly_budget = budget / 24

        is_bad_period = random.random() < 0.15  # Google slightly more stable

        spend = max(0, random.gauss(hourly_budget, hourly_budget * 0.25))
        impressions = int(max(0, random.gauss(spend * 300, spend * 80)))
        clicks = int(max(0, impressions * random.gauss(0.03, 0.008)))

        if is_bad_period:
            installs = int(max(1, clicks * random.gauss(0.04, 0.015)))
            revenue = installs * random.gauss(1.8, 0.6)
        else:
            installs = int(max(1, clicks * random.gauss(0.15, 0.04)))
            revenue = installs * random.gauss(3.5, 1.2)

        cpi = spend / max(installs, 1)
        roas = revenue / max(spend, 0.01)

        return CampaignStats(
            campaign_id=campaign_id,
            impressions=impressions,
            clicks=clicks,
            installs=installs,
            spend=round(spend, 2),
            revenue=round(max(0, revenue), 2),
            cpi=round(cpi, 2),
            roas=round(roas, 2),
        )

    async def set_campaign_budget(self, campaign_id: int, budget: float) -> bool:
        self._budgets[campaign_id] = budget
        return True

    async def set_active_creative(self, campaign_id: int, creative_id: int) -> bool:
        self._active_creatives[campaign_id] = creative_id
        return True

    async def pause_campaign(self, campaign_id: int) -> bool:
        self._paused.add(campaign_id)
        return True

    async def resume_campaign(self, campaign_id: int) -> bool:
        self._paused.discard(campaign_id)
        return True
