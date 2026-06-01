"""Campaign manager: creative rotation and lifecycle management."""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Campaign, Creative, SpendRecord
from app.services.ads_interface import AdsClient

logger = logging.getLogger(__name__)


async def check_and_rotate_creatives(
    db: AsyncSession,
    fb_client: AdsClient,
    google_client: AdsClient,
) -> list[dict]:
    """Check each active campaign's creative performance and rotate if needed.

    Logic:
    - For each campaign, check the last N hours of CPI data.
    - If CPI exceeded the cap for N consecutive hours, rotate to next creative.
    - If no more creatives available, pause the campaign.

    Returns a list of actions taken for reporting.
    """
    fail_hours = settings.app.creative_fail_hours
    actions = []

    result = await db.execute(
        select(Campaign).where(Campaign.is_active == True)
    )
    campaigns = list(result.scalars().all())

    now = datetime.datetime.now()
    check_since = now - datetime.timedelta(hours=fail_hours)

    for campaign in campaigns:
        # Get recent spend records for this campaign
        records_result = await db.execute(
            select(SpendRecord)
            .where(
                and_(
                    SpendRecord.campaign_id == campaign.id,
                    SpendRecord.hour >= check_since,
                )
            )
            .order_by(SpendRecord.hour.desc())
        )
        records = list(records_result.scalars().all())

        if len(records) < fail_hours:
            # Not enough data to judge
            continue

        # Check if CPI exceeded cap in all recent records
        consecutive_bad = all(r.cpi > campaign.cpi_cap for r in records[:fail_hours])

        if not consecutive_bad:
            continue

        # Need to rotate creative
        creatives_result = await db.execute(
            select(Creative)
            .where(
                and_(
                    Creative.campaign_id == campaign.id,
                    Creative.is_active == True,
                )
            )
            .order_by(Creative.sort_order)
        )
        creatives = list(creatives_result.scalars().all())

        next_index = campaign.current_creative_index + 1

        client = fb_client if campaign.platform == "facebook" else google_client

        if next_index >= len(creatives):
            # No more creatives, pause campaign
            campaign.is_active = False
            await client.pause_campaign(campaign.id)
            action_msg = f"Campaign '{campaign.name}' (ID={campaign.id}): no more creatives, PAUSED"
            logger.warning(action_msg)
            actions.append({
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "action": "paused",
                "reason": f"CPI exceeded {campaign.cpi_cap} for {fail_hours} consecutive hours, no more creatives",
            })
        else:
            # Rotate to next creative
            new_creative = creatives[next_index]
            campaign.current_creative_index = next_index
            await client.set_active_creative(campaign.id, new_creative.id)
            action_msg = (
                f"Campaign '{campaign.name}' (ID={campaign.id}): "
                f"rotated creative to '{new_creative.name}' (index={next_index})"
            )
            logger.info(action_msg)
            actions.append({
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "action": "rotated_creative",
                "new_creative": new_creative.name,
                "new_index": next_index,
                "reason": f"CPI exceeded {campaign.cpi_cap} for {fail_hours} consecutive hours",
            })

    await db.commit()
    return actions
