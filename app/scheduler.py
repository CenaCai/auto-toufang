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
from app.services.mock_tiktok import MockTikTokClient

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Platform clients keyed by platform name
_clients: dict[str, AdsClient] = {}


def get_clients() -> dict[str, AdsClient]:
    """Get or create all platform client instances."""
    global _clients
    if not _clients:
        if settings.app.use_mock:
            _clients = {
                "facebook": MockFacebookClient(),
                "google": MockGoogleClient(),
                "tiktok": MockTikTokClient(),
            }
        else:
            # Future: instantiate real API clients here
            raise NotImplementedError("Real API clients not yet implemented")
    return _clients


def get_client_for_platform(platform: str) -> AdsClient:
    """Get the client for a specific platform."""
    clients = get_clients()
    if platform not in clients:
        raise ValueError(f"Unknown platform: {platform}")
    return clients[platform]


async def hourly_job():
    """Runs every hour: rotate creatives, optimize budget, build report, notify."""
    from app.services import budget_optimizer, campaign_manager, report_builder, notifier

    logger.info("=== Hourly job started ===")

    clients = get_clients()

    async with async_session() as db:
        try:
            # 1. Check and rotate creatives
            rotation_actions = await campaign_manager.check_and_rotate_creatives(db, clients)
            if rotation_actions:
                logger.info(f"Creative rotations: {rotation_actions}")

            # 2. Optimize budget allocation
            opt_result = await budget_optimizer.optimize(db, clients)
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
