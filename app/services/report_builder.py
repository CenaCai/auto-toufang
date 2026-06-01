"""Report builder: aggregate data into hourly and daily reports."""

from __future__ import annotations

import datetime
import json
import logging

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, SpendRecord, Report

logger = logging.getLogger(__name__)


async def build_hourly_report(db: AsyncSession) -> dict:
    """Build report for the current hour."""
    now = datetime.datetime.now()
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + datetime.timedelta(hours=1)

    return await _build_report(db, "hourly", hour_start, hour_end)


async def build_daily_report(db: AsyncSession) -> dict:
    """Build report for the current day."""
    now = datetime.datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + datetime.timedelta(days=1)

    return await _build_report(db, "daily", day_start, day_end)


async def _build_report(
    db: AsyncSession,
    report_type: str,
    period_start: datetime.datetime,
    period_end: datetime.datetime,
) -> dict:
    """Core report builder."""
    # Fetch records in period
    result = await db.execute(
        select(SpendRecord).where(
            and_(
                SpendRecord.hour >= period_start,
                SpendRecord.hour < period_end,
            )
        )
    )
    records = list(result.scalars().all())

    # Aggregate by platform
    platform_data = {}
    for platform in ("facebook", "google"):
        p_records = [r for r in records if r.platform == platform]
        if not p_records:
            platform_data[platform] = {
                "total_spend": 0,
                "total_impressions": 0,
                "total_clicks": 0,
                "total_installs": 0,
                "total_revenue": 0,
                "avg_cpi": 0,
                "overall_roas": 0,
                "record_count": 0,
            }
            continue

        total_spend = sum(r.spend for r in p_records)
        total_installs = sum(r.installs for r in p_records)
        total_revenue = sum(r.revenue for r in p_records)

        platform_data[platform] = {
            "total_spend": round(total_spend, 2),
            "total_impressions": sum(r.impressions for r in p_records),
            "total_clicks": sum(r.clicks for r in p_records),
            "total_installs": total_installs,
            "total_revenue": round(total_revenue, 2),
            "avg_cpi": round(total_spend / max(total_installs, 1), 2),
            "overall_roas": round(total_revenue / max(total_spend, 0.01), 2),
            "record_count": len(p_records),
        }

    # Per-campaign breakdown
    campaign_ids = set(r.campaign_id for r in records)
    campaign_details = []
    for cid in campaign_ids:
        c_records = [r for r in records if r.campaign_id == cid]
        c_spend = sum(r.spend for r in c_records)
        c_installs = sum(r.installs for r in c_records)
        c_revenue = sum(r.revenue for r in c_records)

        # Fetch campaign name
        camp_result = await db.execute(select(Campaign).where(Campaign.id == cid))
        camp = camp_result.scalar_one_or_none()

        campaign_details.append({
            "campaign_id": cid,
            "campaign_name": camp.name if camp else f"Campaign #{cid}",
            "platform": c_records[0].platform,
            "spend": round(c_spend, 2),
            "installs": c_installs,
            "revenue": round(c_revenue, 2),
            "cpi": round(c_spend / max(c_installs, 1), 2),
            "roas": round(c_revenue / max(c_spend, 0.01), 2),
        })

    # Build payload
    total_spend = sum(pd["total_spend"] for pd in platform_data.values())
    total_installs = sum(pd["total_installs"] for pd in platform_data.values())
    total_revenue = sum(pd["total_revenue"] for pd in platform_data.values())

    payload = {
        "report_type": report_type,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "generated_at": datetime.datetime.now().isoformat(),
        "summary": {
            "total_spend": round(total_spend, 2),
            "total_installs": total_installs,
            "total_revenue": round(total_revenue, 2),
            "overall_cpi": round(total_spend / max(total_installs, 1), 2),
            "overall_roas": round(total_revenue / max(total_spend, 0.01), 2),
        },
        "platform_breakdown": platform_data,
        "campaign_details": campaign_details,
    }

    # Persist report
    report = Report(
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    payload["report_id"] = report.id
    logger.info(f"{report_type.capitalize()} report #{report.id} generated")

    return payload
