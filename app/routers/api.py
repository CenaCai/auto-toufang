"""JSON API endpoints for campaigns, reports, and manual triggers."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, Creative, SpendRecord, Report
from app.schemas import (
    CampaignCreate, CampaignOut, CampaignUpdate, CreativeCreate,
    ReportOut, TodayStats,
)
from app.scheduler import get_clients, get_client_for_platform, hourly_job

router = APIRouter(prefix="/api", tags=["api"])


# --------------- Campaign CRUD ---------------

@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Campaign).order_by(Campaign.created_at.desc())
    )
    campaigns = result.scalars().all()
    # Eagerly load creatives
    for c in campaigns:
        await db.refresh(c, ["creatives"])
    return campaigns


@router.post("/campaigns", response_model=CampaignOut)
async def create_campaign(data: CampaignCreate, db: AsyncSession = Depends(get_db)):
    if data.platform not in ("facebook", "google", "tiktok"):
        raise HTTPException(400, "platform must be 'facebook', 'google', or 'tiktok'")

    campaign = Campaign(
        name=data.name,
        platform=data.platform,
        external_id=data.external_id,
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


# --------------- Campaign Operations ---------------

@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    """Pause a campaign (stop spending)."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    client = get_client_for_platform(campaign.platform)
    await client.pause_campaign(campaign.id)

    campaign.is_active = False
    await db.commit()
    return {"status": "ok", "campaign_id": campaign_id, "is_active": False}


@router.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    """Resume a paused campaign."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    client = get_client_for_platform(campaign.platform)
    await client.resume_campaign(campaign.id)

    campaign.is_active = True
    await db.commit()
    return {"status": "ok", "campaign_id": campaign_id, "is_active": True}


@router.post("/campaigns/{campaign_id}/switch-creative")
async def switch_creative(
    campaign_id: int,
    creative_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Switch active creative. If creative_id given, use that; otherwise rotate to next."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Load creatives
    creatives_result = await db.execute(
        select(Creative)
        .where(Creative.campaign_id == campaign_id, Creative.is_active == True)
        .order_by(Creative.sort_order)
    )
    creatives = list(creatives_result.scalars().all())
    if not creatives:
        raise HTTPException(400, "No active creatives available for this campaign")

    client = get_client_for_platform(campaign.platform)

    if creative_id is not None:
        # Switch to specific creative
        target = next((c for c in creatives if c.id == creative_id), None)
        if not target:
            raise HTTPException(404, "Creative not found or not active in this campaign")
        new_index = creatives.index(target)
    else:
        # Rotate to next
        new_index = campaign.current_creative_index + 1
        if new_index >= len(creatives):
            new_index = 0  # loop back

    target_creative = creatives[new_index]
    campaign.current_creative_index = new_index
    await client.set_active_creative(campaign.id, target_creative.id)
    await db.commit()

    return {
        "status": "ok",
        "campaign_id": campaign_id,
        "new_creative_id": target_creative.id,
        "new_creative_name": target_creative.name,
        "creative_index": new_index,
    }


@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a campaign and all its data."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Pause on platform first
    client = get_client_for_platform(campaign.platform)
    await client.pause_campaign(campaign.id)

    await db.delete(campaign)
    await db.commit()
    return {"status": "ok", "deleted": campaign_id}


@router.post("/campaigns/{campaign_id}/creatives")
async def add_creative(
    campaign_id: int,
    data: CreativeCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new creative to a campaign."""
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Get max sort_order
    max_order_result = await db.execute(
        select(func.coalesce(func.max(Creative.sort_order), -1))
        .where(Creative.campaign_id == campaign_id)
    )
    max_order = max_order_result.scalar_one()

    creative = Creative(
        campaign_id=campaign_id,
        name=data.name,
        asset_url=data.asset_url,
        sort_order=data.sort_order if data.sort_order else max_order + 1,
    )
    db.add(creative)
    await db.commit()
    await db.refresh(creative)
    return {"status": "ok", "creative_id": creative.id, "name": creative.name}


@router.delete("/campaigns/{campaign_id}/creatives/{creative_id}")
async def remove_creative(
    campaign_id: int,
    creative_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Remove a creative from a campaign (soft-delete by marking inactive)."""
    result = await db.execute(
        select(Creative).where(Creative.id == creative_id, Creative.campaign_id == campaign_id)
    )
    creative = result.scalar_one_or_none()
    if not creative:
        raise HTTPException(404, "Creative not found")

    creative.is_active = False
    await db.commit()
    return {"status": "ok", "creative_id": creative_id, "is_active": False}


# --------------- Reports ---------------
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

    from app.config import settings
    from app.schemas import PlatformStats

    platforms_stats = {}
    total_installs = 0
    total_spend = 0.0

    for platform in ("facebook", "google", "tiktok"):
        p_records = [r for r in records if r.platform == platform]
        p_spend = sum(r.spend for r in p_records)
        p_installs = sum(r.installs for r in p_records)
        p_revenue = sum(r.revenue for r in p_records)
        total_spend += p_spend
        total_installs += p_installs
        platforms_stats[platform] = PlatformStats(
            spend=round(p_spend, 2),
            avg_cpi=round(p_spend / max(p_installs, 1), 2),
            roas=round(p_revenue / max(p_spend, 0.01), 2),
            installs=p_installs,
        )

    # Active campaigns count
    camp_result = await db.execute(
        select(func.count()).select_from(Campaign).where(Campaign.is_active == True)
    )
    active_count = camp_result.scalar_one()

    return TodayStats(
        date=today_start.strftime("%Y-%m-%d"),
        total_spend=round(total_spend, 2),
        daily_cap=settings.app.daily_spend_cap,
        platforms=platforms_stats,
        active_campaigns=active_count,
        total_installs=total_installs,
    )


@router.post("/seed-demo")
async def seed_demo_data(db: AsyncSession = Depends(get_db)):
    """Seed database with demo campaigns for testing."""
    demo_campaigns = [
        CampaignCreate(
            name="FB - Game Install US",
            platform="facebook",
            external_id="120210123456789",
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
            external_id="120210987654321",
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
            external_id="18394027561",
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
            external_id="18394027562",
            budget_cap=1800.0,
            cpi_cap=3.5,
            roas_threshold=1.1,
            creatives=[
                {"name": "KR Video v1", "asset_url": "https://example.com/g_kr_v1.mp4"},
                {"name": "KR HTML5", "asset_url": "https://example.com/g_kr_html5.zip"},
                {"name": "KR Display", "asset_url": "https://example.com/g_kr_display.zip"},
            ],
        ),
        CampaignCreate(
            name="TikTok - Game Install US",
            platform="tiktok",
            external_id="1790663820000001",
            budget_cap=2000.0,
            cpi_cap=2.8,
            roas_threshold=1.2,
            creatives=[
                {"name": "Short Video v1", "asset_url": "https://example.com/tt_us_v1.mp4"},
                {"name": "Short Video v2", "asset_url": "https://example.com/tt_us_v2.mp4"},
                {"name": "Spark Ad", "asset_url": "https://example.com/tt_us_spark.mp4"},
            ],
        ),
        CampaignCreate(
            name="TikTok - Game Install SEA",
            platform="tiktok",
            external_id="1790663820000002",
            budget_cap=1200.0,
            cpi_cap=1.5,
            roas_threshold=1.0,
            creatives=[
                {"name": "SEA Video v1", "asset_url": "https://example.com/tt_sea_v1.mp4"},
                {"name": "SEA UGC Style", "asset_url": "https://example.com/tt_sea_ugc.mp4"},
            ],
        ),
    ]

    created = []
    for data in demo_campaigns:
        campaign = Campaign(
            name=data.name,
            platform=data.platform,
            external_id=data.external_id,
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
