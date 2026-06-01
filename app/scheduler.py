"""APScheduler job definitions for hourly and daily cycles."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import async_session
from app.services.ads_interface import AdsClient
from app.services.mock_facebook import MockFacebookClient
from app.services.mock_google import MockGoogleClient

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Platform clients (global singletons)
_fb_client: AdsClient | None = None
_google_client: AdsClient | None = None


def get_clients() -> tuple[AdsClient, AdsClient]:
    """Get or create platform client instances."""
    global _fb_client, _google_client
    if _fb_client is None:
        if settings.app.use_mock:
            _fb_client = MockFacebookClient()
            _google_client = MockGoogleClient()
        else:
            # Future: instantiate real API clients here
            raise NotImplementedError("Real API clients not yet implemented")
    return _fb_client, _google_client


async def hourly_job():
    """Runs every hour: rotate creatives, optimize budget, build report, notify."""
    from app.services import budget_optimizer, campaign_manager, report_builder, notifier

    logger.info("=== Hourly job started ===")

    fb, google = get_clients()

    async with async_session() as db:
        try:
            # 1. Check and rotate creatives
            rotation_actions = await campaign_manager.check_and_rotate_creatives(db, fb, google)
            if rotation_actions:
                logger.info(f"Creative rotations: {rotation_actions}")

            # 2. Optimize budget allocation
            opt_result = await budget_optimizer.optimize(db, fb, google)
            logger.info(f"Optimization: {opt_result.action}, allocation={opt_result.budget_allocation}")

            # 3. Build hourly report
            report = await report_builder.build_hourly_report(db)

            # Add optimization info to report
            report["optimization"] = {
                "action": opt_result.action,
                "budget_allocation": opt_result.budget_allocation,
                "daily_spend_total": opt_result.daily_spend_total,
                "daily_cap": opt_result.daily_cap,
            }
            if rotation_actions:
                report["creative_rotations"] = rotation_actions

            # 4. Send notifications
            notify_results = await notifier.send_report(report)
            logger.info(f"Notifications: {notify_results}")

        except Exception as e:
            logger.exception(f"Hourly job failed: {e}")

    logger.info("=== Hourly job completed ===")


async def daily_job():
    """Runs daily: build daily summary report and notify."""
    from app.services import report_builder, notifier

    logger.info("=== Daily job started ===")

    async with async_session() as db:
        try:
            report = await report_builder.build_daily_report(db)
            notify_results = await notifier.send_report(report)
            logger.info(f"Daily report notifications: {notify_results}")
        except Exception as e:
            logger.exception(f"Daily job failed: {e}")

    logger.info("=== Daily job completed ===")


def start_scheduler():
    """Configure and start the scheduler."""
    # Hourly at :05 (give ad platforms time to settle data)
    scheduler.add_job(
        hourly_job,
        CronTrigger(minute=5),
        id="hourly_optimization",
        name="Hourly optimization + report",
        replace_existing=True,
    )

    # Daily at 00:30
    scheduler.add_job(
        daily_job,
        CronTrigger(hour=0, minute=30),
        id="daily_report",
        name="Daily summary report",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: hourly@:05, daily@00:30")


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
