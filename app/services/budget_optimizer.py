"""Budget optimization engine.

Core decision logic: evaluate CPI + ROAS per platform, shift budget accordingly.
"""

from __future__ import annotations

import datetime
import logging
from typing import Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Campaign, SpendRecord
from app.schemas import CampaignStats, OptimizationResult, PlatformSummary
from app.services.ads_interface import AdsClient

logger = logging.getLogger(__name__)


def _evaluate_platform(
    stats_list: list[CampaignStats],
    campaigns: dict[int, Campaign],
) -> PlatformSummary | None:
    """Aggregate stats for one platform and determine health."""
    if not stats_list:
        return None

    total_spend = sum(s.spend for s in stats_list)
    total_installs = sum(s.installs for s in stats_list)
    total_revenue = sum(s.revenue for s in stats_list)

    avg_cpi = total_spend / max(total_installs, 1)
    overall_roas = total_revenue / max(total_spend, 0.01)

    # A platform is "healthy" if avg CPI is within cap AND ROAS meets threshold
    avg_cpi_cap = sum(
        c.cpi_cap for cid, c in campaigns.items() if cid in {s.campaign_id for s in stats_list}
    ) / max(len(stats_list), 1)

    avg_roas_threshold = sum(
        (c.roas_threshold or settings.app.default_roas_threshold)
        for cid, c in campaigns.items()
        if cid in {s.campaign_id for s in stats_list}
    ) / max(len(stats_list), 1)

    is_healthy = avg_cpi <= avg_cpi_cap and overall_roas >= avg_roas_threshold
    platform = stats_list[0].campaign_id  # placeholder, set by caller

    return PlatformSummary(
        platform="",  # set by caller
        total_spend=round(total_spend, 2),
        avg_cpi=round(avg_cpi, 2),
        overall_roas=round(overall_roas, 2),
        campaign_count=len(stats_list),
        is_healthy=is_healthy,
    )


async def get_today_total_spend(db: AsyncSession) -> float:
    """Sum of all spend records for today."""
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(SpendRecord.spend), 0.0)).where(
            SpendRecord.hour >= today_start
        )
    )
    return float(result.scalar_one())


async def optimize(
    db: AsyncSession,
    fb_client: AdsClient,
    google_client: AdsClient,
) -> OptimizationResult:
    """Run one optimization cycle.

    1. Fetch stats from both platforms for all active campaigns.
    2. Evaluate platform health.
    3. Decide budget allocation.
    4. Apply new budgets.
    5. Record spend data.
    """
    now = datetime.datetime.now()

    # Get all active campaigns grouped by platform
    result = await db.execute(
        select(Campaign).where(Campaign.is_active == True)
    )
    campaigns = list(result.scalars().all())
    campaign_map = {c.id: c for c in campaigns}

    fb_campaigns = [c for c in campaigns if c.platform == "facebook"]
    google_campaigns = [c for c in campaigns if c.platform == "google"]

    # Fetch stats
    fb_stats: list[CampaignStats] = []
    for c in fb_campaigns:
        stats = await fb_client.get_campaign_stats(c.id)
        fb_stats.append(stats)

    google_stats: list[CampaignStats] = []
    for c in google_campaigns:
        stats = await google_client.get_campaign_stats(c.id)
        google_stats.append(stats)

    # Evaluate
    fb_summary = _evaluate_platform(fb_stats, campaign_map)
    if fb_summary:
        fb_summary.platform = "facebook"

    google_summary = _evaluate_platform(google_stats, campaign_map)
    if google_summary:
        google_summary.platform = "google"

    # Check daily cap
    today_spend = await get_today_total_spend(db)
    daily_cap = settings.app.daily_spend_cap
    remaining_budget = max(0, daily_cap - today_spend)

    # Decision
    fb_healthy = fb_summary.is_healthy if fb_summary else False
    google_healthy = google_summary.is_healthy if google_summary else False
    ratio = settings.app.budget_shift_ratio

    if remaining_budget <= 0:
        action = "paused_all"
        allocation = {"facebook": 0.0, "google": 0.0}
        # Pause all campaigns
        for c in campaigns:
            client = fb_client if c.platform == "facebook" else google_client
            await client.pause_campaign(c.id)
    elif fb_healthy and not google_healthy:
        action = "shift_to_facebook"
        allocation = {
            "facebook": round(remaining_budget * ratio, 2),
            "google": round(remaining_budget * (1 - ratio), 2),
        }
    elif google_healthy and not fb_healthy:
        action = "shift_to_google"
        allocation = {
            "facebook": round(remaining_budget * (1 - ratio), 2),
            "google": round(remaining_budget * ratio, 2),
        }
    else:
        # Both healthy, both unhealthy, or one platform has no campaigns
        action = "split_even"
        allocation = {
            "facebook": round(remaining_budget * 0.5, 2),
            "google": round(remaining_budget * 0.5, 2),
        }

    # Apply budgets proportionally to campaigns
    if remaining_budget > 0:
        for platform, campaigns_list, client in [
            ("facebook", fb_campaigns, fb_client),
            ("google", google_campaigns, google_client),
        ]:
            platform_budget = allocation.get(platform, 0)
            n = len(campaigns_list)
            if n > 0:
                per_campaign = platform_budget / n
                for c in campaigns_list:
                    capped = min(per_campaign, c.budget_cap)
                    await client.set_campaign_budget(c.id, capped)

    # Record spend data
    all_stats = [(s, "facebook") for s in fb_stats] + [(s, "google") for s in google_stats]
    hour = now.replace(minute=0, second=0, microsecond=0)

    for stats, platform in all_stats:
        record = SpendRecord(
            campaign_id=stats.campaign_id,
            platform=platform,
            hour=hour,
            impressions=stats.impressions,
            clicks=stats.clicks,
            installs=stats.installs,
            spend=stats.spend,
            revenue=stats.revenue,
            cpi=stats.cpi,
            roas=stats.roas,
            creative_id=None,
        )
        db.add(record)

    await db.commit()

    logger.info(f"Optimization complete: {action}, allocation={allocation}")

    return OptimizationResult(
        timestamp=now,
        daily_spend_total=round(today_spend + sum(s.spend for s, _ in all_stats), 2),
        daily_cap=daily_cap,
        fb_summary=fb_summary,
        google_summary=google_summary,
        action=action,
        budget_allocation=allocation,
    )
