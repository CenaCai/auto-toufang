"""Budget optimization engine.

Core decision logic: evaluate CPI + ROAS per platform, shift budget accordingly.
Supports any number of platforms (Facebook, Google, TikTok, etc.).
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Campaign, SpendRecord
from app.schemas import CampaignStats, OptimizationResult, PlatformSummary
from app.services.ads_interface import AdsClient

logger = logging.getLogger(__name__)

# All supported platform names
PLATFORMS = ("facebook", "google", "tiktok")


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

    campaign_ids_in_stats = {s.campaign_id for s in stats_list}
    relevant_campaigns = [c for cid, c in campaigns.items() if cid in campaign_ids_in_stats]

    avg_cpi_cap = sum(c.cpi_cap for c in relevant_campaigns) / max(len(relevant_campaigns), 1)
    avg_roas_threshold = sum(
        (c.roas_threshold or settings.app.default_roas_threshold)
        for c in relevant_campaigns
    ) / max(len(relevant_campaigns), 1)

    is_healthy = avg_cpi <= avg_cpi_cap and overall_roas >= avg_roas_threshold

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
    clients: dict[str, AdsClient],
) -> OptimizationResult:
    """Run one optimization cycle across all platforms.

    1. Fetch stats from all platforms for all active campaigns.
    2. Evaluate platform health.
    3. Decide budget allocation based on which platforms are healthy.
    4. Apply new budgets.
    5. Record spend data.
    """
    now = datetime.datetime.now()

    # Get all active campaigns
    result = await db.execute(
        select(Campaign).where(Campaign.is_active == True)
    )
    campaigns = list(result.scalars().all())
    campaign_map = {c.id: c for c in campaigns}

    # Group campaigns by platform and fetch stats
    platform_campaigns: dict[str, list[Campaign]] = {p: [] for p in PLATFORMS}
    platform_stats: dict[str, list[CampaignStats]] = {p: [] for p in PLATFORMS}
    platform_summaries: dict[str, PlatformSummary] = {}

    for c in campaigns:
        if c.platform in platform_campaigns:
            platform_campaigns[c.platform].append(c)

    for platform, camp_list in platform_campaigns.items():
        if platform not in clients:
            continue
        client = clients[platform]
        for c in camp_list:
            stats = await client.get_campaign_stats(c.id)
            platform_stats[platform].append(stats)

    # Evaluate each platform
    for platform in PLATFORMS:
        summary = _evaluate_platform(platform_stats[platform], campaign_map)
        if summary:
            summary.platform = platform
            platform_summaries[platform] = summary

    # Check daily cap
    today_spend = await get_today_total_spend(db)
    daily_cap = settings.app.daily_spend_cap
    remaining_budget = max(0, daily_cap - today_spend)

    # Decision: identify healthy platforms
    healthy_platforms = [p for p, s in platform_summaries.items() if s.is_healthy]
    active_platforms = list(platform_summaries.keys())  # platforms that have campaigns
    ratio = settings.app.budget_shift_ratio

    if remaining_budget <= 0:
        action = "paused_all"
        allocation = {p: 0.0 for p in PLATFORMS}
        for c in campaigns:
            if c.platform in clients:
                await clients[c.platform].pause_campaign(c.id)
    elif len(healthy_platforms) == 0 or len(healthy_platforms) == len(active_platforms):
        # All healthy or all unhealthy: split evenly among active platforms
        action = "split_even"
        n_active = max(len(active_platforms), 1)
        allocation = {p: round(remaining_budget / n_active, 2) if p in active_platforms else 0.0 for p in PLATFORMS}
    elif len(healthy_platforms) == 1:
        # One healthy: give it the lion's share
        winner = healthy_platforms[0]
        losers = [p for p in active_platforms if p != winner]
        loser_share = (1 - ratio) / max(len(losers), 1)
        action = f"shift_to_{winner}"
        allocation = {}
        for p in PLATFORMS:
            if p == winner:
                allocation[p] = round(remaining_budget * ratio, 2)
            elif p in losers:
                allocation[p] = round(remaining_budget * loser_share, 2)
            else:
                allocation[p] = 0.0
    else:
        # Multiple healthy platforms: split budget proportionally among healthy ones
        unhealthy = [p for p in active_platforms if p not in healthy_platforms]
        # Healthy platforms share the bulk, unhealthy get a small slice each
        healthy_total = ratio
        unhealthy_each = (1 - ratio) / max(len(unhealthy), 1) if unhealthy else 0
        healthy_each = healthy_total / len(healthy_platforms)

        action = "shift_to_healthy"
        allocation = {}
        for p in PLATFORMS:
            if p in healthy_platforms:
                allocation[p] = round(remaining_budget * healthy_each, 2)
            elif p in unhealthy:
                allocation[p] = round(remaining_budget * unhealthy_each, 2)
            else:
                allocation[p] = 0.0

    # Apply budgets proportionally to campaigns within each platform
    if remaining_budget > 0:
        for platform in PLATFORMS:
            if platform not in clients:
                continue
            client = clients[platform]
            camp_list = platform_campaigns.get(platform, [])
            platform_budget = allocation.get(platform, 0)
            n = len(camp_list)
            if n > 0:
                per_campaign = platform_budget / n
                for c in camp_list:
                    capped = min(per_campaign, c.budget_cap)
                    await client.set_campaign_budget(c.id, capped)

    # Record spend data
    hour = now.replace(minute=0, second=0, microsecond=0)
    total_new_spend = 0.0

    for platform in PLATFORMS:
        for stats in platform_stats[platform]:
            total_new_spend += stats.spend
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
        daily_spend_total=round(today_spend + total_new_spend, 2),
        daily_cap=daily_cap,
        platform_summaries=platform_summaries,
        action=action,
        budget_allocation=allocation,
    )
