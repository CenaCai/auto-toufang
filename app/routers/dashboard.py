"""Dashboard routes: HTML pages for report viewing."""

from __future__ import annotations

import json
import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Campaign, Creative, SpendRecord, Report
from app.config import settings

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.head("/", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Today's stats
    result = await db.execute(
        select(SpendRecord).where(SpendRecord.hour >= today_start)
    )
    records = list(result.scalars().all())

    fb_records = [r for r in records if r.platform == "facebook"]
    google_records = [r for r in records if r.platform == "google"]

    fb_spend = sum(r.spend for r in fb_records)
    google_spend = sum(r.spend for r in google_records)
    total_spend = fb_spend + google_spend
    fb_installs = sum(r.installs for r in fb_records)
    google_installs = sum(r.installs for r in google_records)
    fb_revenue = sum(r.revenue for r in fb_records)
    google_revenue = sum(r.revenue for r in google_records)

    # Active campaigns
    camp_result = await db.execute(
        select(func.count()).select_from(Campaign).where(Campaign.is_active == True)
    )
    active_campaigns = camp_result.scalar_one()

    # Recent reports
    report_result = await db.execute(
        select(Report).order_by(Report.created_at.desc()).limit(10)
    )
    recent_reports = report_result.scalars().all()

    return templates.TemplateResponse(name="dashboard.html", request=request, context={
        "date": today_start.strftime("%Y-%m-%d"),
        "total_spend": round(total_spend, 2),
        "daily_cap": settings.app.daily_spend_cap,
        "fb_spend": round(fb_spend, 2),
        "google_spend": round(google_spend, 2),
        "fb_cpi": round(fb_spend / max(fb_installs, 1), 2),
        "google_cpi": round(google_spend / max(google_installs, 1), 2),
        "fb_roas": round(fb_revenue / max(fb_spend, 0.01), 2),
        "google_roas": round(google_revenue / max(google_spend, 0.01), 2),
        "active_campaigns": active_campaigns,
        "total_installs": fb_installs + google_installs,
        "recent_reports": recent_reports,
        "spend_pct": round(total_spend / max(settings.app.daily_spend_cap, 1) * 100, 1),
    })


@router.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Campaign).order_by(Campaign.created_at.desc())
    )
    campaigns = list(result.scalars().all())

    # Load creatives and compute platform_url for each
    campaign_data = []
    for c in campaigns:
        await db.refresh(c, ["creatives"])
        # Compute platform URL
        platform_url = ""
        if c.external_id:
            if c.platform == "facebook":
                platform_url = f"https://business.facebook.com/adsmanager/manage/campaigns?act=&selected_campaign_ids={c.external_id}"
            elif c.platform == "google":
                platform_url = f"https://ads.google.com/aw/campaigns?campaignId={c.external_id}"
        campaign_data.append({
            "id": c.id,
            "name": c.name,
            "platform": c.platform,
            "external_id": c.external_id or "",
            "budget_cap": c.budget_cap,
            "cpi_cap": c.cpi_cap,
            "roas_threshold": c.roas_threshold,
            "current_creative_index": c.current_creative_index,
            "is_active": c.is_active,
            "platform_url": platform_url,
            "creatives": sorted(c.creatives, key=lambda x: x.sort_order),
        })

    return templates.TemplateResponse(name="campaigns.html", request=request, context={
        "campaigns": campaign_data,
    })


@router.get("/reports/hourly", response_class=HTMLResponse)
async def hourly_reports(
    request: Request,
    date: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Report).where(Report.report_type == "hourly").order_by(Report.period_start.desc())

    if date:
        try:
            d = datetime.date.fromisoformat(date)
            day_start = datetime.datetime.combine(d, datetime.time.min)
            day_end = day_start + datetime.timedelta(days=1)
            query = query.where(
                and_(Report.period_start >= day_start, Report.period_start < day_end)
            )
        except ValueError:
            pass

    query = query.limit(48)
    result = await db.execute(query)
    reports = result.scalars().all()

    # Parse payloads
    parsed = []
    for r in reports:
        try:
            payload = json.loads(r.payload)
        except json.JSONDecodeError:
            payload = {}
        parsed.append({"report": r, "data": payload})

    return templates.TemplateResponse(name="reports.html", request=request, context={
        "report_type": "hourly",
        "title": "小时报",
        "reports": parsed,
        "filter_date": date or "",
    })


@router.get("/reports/daily", response_class=HTMLResponse)
async def daily_reports(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Report)
        .where(Report.report_type == "daily")
        .order_by(Report.period_start.desc())
        .limit(30)
    )
    reports = result.scalars().all()

    parsed = []
    for r in reports:
        try:
            payload = json.loads(r.payload)
        except json.JSONDecodeError:
            payload = {}
        parsed.append({"report": r, "data": payload})

    return templates.TemplateResponse(name="reports.html", request=request, context={
        "report_type": "daily",
        "title": "日报",
        "reports": parsed,
        "filter_date": "",
    })


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(report_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()

    if not report:
        return HTMLResponse("<h1>Report not found</h1>", status_code=404)

    try:
        payload = json.loads(report.payload)
    except json.JSONDecodeError:
        payload = {}

    return templates.TemplateResponse(name="report_detail.html", request=request, context={
        "report": report,
        "data": payload,
    })
