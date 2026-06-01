"""Abstract base class for ads platform clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from app.schemas import CampaignStats


class AdsClient(ABC):
    """Interface for interacting with an ads platform (Facebook / Google Ads).

    Implement this class for each platform. Mock implementations are provided
    for development; swap to real API clients by changing config.use_mock.
    """

    platform: str  # "facebook" or "google"

    @abstractmethod
    async def get_campaign_stats(
        self, campaign_id: int, hour: date | None = None
    ) -> CampaignStats:
        """Fetch performance stats for a campaign in the current hour."""
        ...

    @abstractmethod
    async def set_campaign_budget(self, campaign_id: int, budget: float) -> bool:
        """Update the daily budget for a campaign. Returns True on success."""
        ...

    @abstractmethod
    async def set_active_creative(
        self, campaign_id: int, creative_id: int
    ) -> bool:
        """Switch the active creative for a campaign."""
        ...

    @abstractmethod
    async def pause_campaign(self, campaign_id: int) -> bool:
        """Pause a campaign."""
        ...

    @abstractmethod
    async def resume_campaign(self, campaign_id: int) -> bool:
        """Resume a paused campaign."""
        ...
