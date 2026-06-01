"""JSON API endpoints for campaigns, reports, and manual triggers."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, Creative, SpendRecord, Report
from app.schemas import (
    CampaignCreate, CampaignOut, CampaignUpdate,
    ReportOut, TodayStats,
)
from app.scheduler import get_clients, hourly_job

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Campaign).order_by(Campaign.created_at.desc())
    )
    return result.scalars().all()


@router.post("/campaigns", response_model=CampaignOut)
async def create_campaign(data: CampaignCreate, db: AsyncSession = Depends(get_db)):
    if data.platform not in ("facebook", "google"):
        raise HTTPException(400, "platform must be 'facebook' or 'google'")

    campaign = Campaign(
        name=data.name,
        platform=data.platform,
        budget_cap=data.budget_cap,
        cpi_cap=data.cpi_cap,
        roas_threshold=data.roas_threshold,
    )
    db.add(campaign)
    await db.flush()

    for i, c in enumerate(data.creatives):
        creative = Creative(
            campaign_id=campaign.id,
            name=c.name,
            asset_url=c.asset_url,
            sort_order=c.sort_order if c.sort_order else i,
        )
        db.add(creative)

    await db.commit()
    await db.refresh(campaign)

    # Re-fetch with creatives loaded
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign.id)
    )
    camp = result.scalar_one()
    # Eagerly load creatives
    await db.refresh(camp, ["creatives"])
    return camp


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int,
    data: CampaignUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(campaign, field, value)

    await db.commit()
    await db.refresh(campaign, ["creatives"])
    return campaign


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    report_type: str | None = None,
    date: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    query = select(Report).order_by(Report.created_at.desc()).limit(limit)

    if report_type:
        query = query.where(Report.report_type == report_type)

    if date:
        try:
            d = datetime.date.fromisoformat(date)
            day_start = datetime.datetime.combine(d, datetime.time.min)
            day_end = day_start + datetime.timedelta(days=1)
            query = query.where(
                and_(Report.period_start >= day_start, Report.period_start < day_end)
            )
        except ValueError:
            raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/optimize/trigger")
async def trigger_optimization():
    """Manually trigger an optimization cycle."""
    await hourly_job()
    return {"status": "ok", "message": "Optimization cycle triggered"}


@router.get("/stats/today", response_model=TodayStats)
async def today_stats(db: AsyncSession = Depends(get_db)):
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(SpendRecord).where(SpendRecord.hour >= today_start)
    )
    records = list(result.scalars().all())

    fb_records = [r for r in records if r.platform == "facebook"]
    google_records = [r for r in records if r.platform == "google"]

    fb_spend = sum(r.spend for r in fb_records)
    google_spend = sum(r.spend for r in google_records)
    fb_installs = sum(r.installs for r in fb_records)
    google_installs = sum(r.installs for r in google_records)
    fb_revenue = sum(r.revenue for r in fb_records)
    google_revenue = sum(r.revenue for r in google_records)

    # Active campaigns count
    camp_result = await db.execute(
        select(func.count()).select_from(Campaign).where(Campaign.is_active == True)
    )
    active_count = camp_result.scalar_one()

    from app.config import settings

    return TodayStats(
        date=today_start.strftime("%Y-%m-%d"),
        total_spend=round(fb_spend + google_spend, 2),
        daily_cap=settings.app.daily_spend_cap,
        fb_spend=round(fb_spend, 2),
        google_spend=round(google_spend, 2),
        fb_avg_cpi=round(fb_spend / max(fb_installs, 1), 2),
        google_avg_cpi=round(google_spend / max(google_installs, 1), 2),
        fb_roas=round(fb_revenue / max(fb_spend, 0.01), 2),
        google_roas=round(google_revenue / max(google_spend, 0.01), 2),
        active_campaigns=active_count,
        total_installs=fb_installs + google_installs,
    )


@router.post("/seed-demo")
async def seed_demo_data(db: AsyncSession = Depends(get_db)):
    """Seed database with demo campaigns for testing."""
    demo_campaigns = [
        CampaignCreate(
            name="FB - Game Install US",
            platform="facebook",
            budget_cap=2000.0,
            cpi_cap=3.0,
            roas_threshold=1.2,
            creatives=[
                {"name": "Video Ad v1", "asset_url": "https://example.com/fb_v1.mp4"},
                {"name": "Video Ad v2", "asset_url": "https://example.com/fb_v2.mp4"},
                {"name": "Image Carousel", "asset_url": "https://example.com/fb_carousel.zip"},
            ],
        ),
        CampaignCreate(
            name="FB - Game Install JP",
            platform="facebook",
            budget_cap=1500.0,
            cpi_cap=4.0,
            roas_threshold=1.0,
            creatives=[
                {"name": "JP Video v1", "asset_url": "https://example.com/fb_jp_v1.mp4"},
                {"name": "JP Playable", "asset_url": "https://example.com/fb_jp_playable.html"},
            ],
        ),
        CampaignCreate(
            name="Google - UAC US",
            platform="google",
            budget_cap=2500.0,
            cpi_cap=2.5,
            roas_threshold=1.3,
            creatives=[
                {"name": "UAC Asset Set A", "asset_url": "https://example.com/g_us_a.zip"},
                {"name": "UAC Asset Set B", "asset_url": "https://example.com/g_us_b.zip"},
            ],
        ),
        CampaignCreate(
            name="Google - UAC KR",
            platform="google",
            budget_cap=1800.0,
            cpi_cap=3.5,
            roas_threshold=1.1,
            creatives=[
                {"name": "KR Video v1", "asset_url": "https://example.com/g_kr_v1.mp4"},
                {"name": "KR HTML5", "asset_url": "https://example.com/g_kr_html5.zip"},
                {"name": "KR Display", "asset_url": "https://example.com/g_kr_display.zip"},
            ],
        ),
    ]

    created = []
    for data in demo_campaigns:
        campaign = Campaign(
            name=data.name,
            platform=data.platform,
            budget_cap=data.budget_cap,
            cpi_cap=data.cpi_cap,
            roas_threshold=data.roas_threshold,
        )
        db.add(campaign)
        await db.flush()

        for i, c in enumerate(data.creatives):
            creative = Creative(
                campaign_id=campaign.id,
                name=c.name,
                asset_url=c.asset_url,
                sort_order=i,
            )
            db.add(creative)

        created.append(campaign.name)

    await db.commit()
    return {"status": "ok", "created": created}
