"""Notification dispatcher: Feishu webhook + Email SMTP."""

from __future__ import annotations

import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_report(report: dict) -> dict[str, bool]:
    """Send report to all configured channels. Returns status per channel."""
    results = {}

    if settings.notifications.feishu.enabled:
        results["feishu"] = await _send_feishu(report)

    if settings.notifications.email.enabled:
        results["email"] = await _send_email(report)

    return results


async def _send_feishu(report: dict) -> bool:
    """Send report to Feishu via webhook (Interactive Message Card)."""
    try:
        webhook_url = settings.notifications.feishu.webhook_url
        report_type = report.get("report_type", "unknown")
        summary = report.get("summary", {})
        fb = report.get("platform_breakdown", {}).get("facebook", {})
        google = report.get("platform_breakdown", {}).get("google", {})
        tiktok = report.get("platform_breakdown", {}).get("tiktok", {})

        title = f"{'小时报' if report_type == 'hourly' else '日报'} - 广告投放报告"

        # Build Feishu card message
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue" if report_type == "hourly" else "purple",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"**时间**: {report.get('period_start', '')} ~ {report.get('period_end', '')}\n"
                                f"**总花费**: ${summary.get('total_spend', 0):,.2f}\n"
                                f"**总安装**: {summary.get('total_installs', 0):,}\n"
                                f"**总收入**: ${summary.get('total_revenue', 0):,.2f}\n"
                                f"**整体CPI**: ${summary.get('overall_cpi', 0):.2f}\n"
                                f"**整体ROAS**: {summary.get('overall_roas', 0):.2f}"
                            ),
                        },
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"**Facebook**: 花费 ${fb.get('total_spend', 0):,.2f} | "
                                f"CPI ${fb.get('avg_cpi', 0):.2f} | "
                                f"ROAS {fb.get('overall_roas', 0):.2f}\n"
                                f"**Google Ads**: 花费 ${google.get('total_spend', 0):,.2f} | "
                                f"CPI ${google.get('avg_cpi', 0):.2f} | "
                                f"ROAS {google.get('overall_roas', 0):.2f}\n"
                                f"**TikTok Ads**: 花费 ${tiktok.get('total_spend', 0):,.2f} | "
                                f"CPI ${tiktok.get('avg_cpi', 0):.2f} | "
                                f"ROAS {tiktok.get('overall_roas', 0):.2f}"
                            ),
                        },
                    },
                ],
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=card, timeout=10)
            resp.raise_for_status()
            logger.info(f"Feishu notification sent for {report_type} report")
            return True

    except Exception as e:
        logger.error(f"Feishu notification failed: {e}")
        return False


async def _send_email(report: dict) -> bool:
    """Send report via SMTP email."""
    try:
        cfg = settings.notifications.email
        report_type = report.get("report_type", "unknown")
        summary = report.get("summary", {})
        fb = report.get("platform_breakdown", {}).get("facebook", {})
        google = report.get("platform_breakdown", {}).get("google", {})

        subject = f"广告投放{'小时报' if report_type == 'hourly' else '日报'} - {report.get('period_start', '')}"

        fb = report.get("platform_breakdown", {}).get("facebook", {})
        google = report.get("platform_breakdown", {}).get("google", {})
        tiktok = report.get("platform_breakdown", {}).get("tiktok", {})

        # Build HTML email body
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #333;">{'小时报' if report_type == 'hourly' else '日报'} - 广告投放报告</h2>
            <p>时间: {report.get('period_start', '')} ~ {report.get('period_end', '')}</p>

            <h3>总览</h3>
            <table style="border-collapse: collapse; width: 100%;">
                <tr style="background: #f5f5f5;">
                    <td style="padding: 8px; border: 1px solid #ddd;">总花费</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${summary.get('total_spend', 0):,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">总安装</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{summary.get('total_installs', 0):,}</td>
                </tr>
                <tr style="background: #f5f5f5;">
                    <td style="padding: 8px; border: 1px solid #ddd;">总收入</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${summary.get('total_revenue', 0):,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">整体CPI</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${summary.get('overall_cpi', 0):.2f}</td>
                </tr>
                <tr style="background: #f5f5f5;">
                    <td style="padding: 8px; border: 1px solid #ddd;">整体ROAS</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{summary.get('overall_roas', 0):.2f}</td>
                </tr>
            </table>

            <h3>平台明细</h3>
            <table style="border-collapse: collapse; width: 100%;">
                <tr style="background: #4267B2; color: white;">
                    <th style="padding: 8px;">Facebook</th>
                    <th style="padding: 8px;">花费</th>
                    <th style="padding: 8px;">CPI</th>
                    <th style="padding: 8px;">ROAS</th>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">-</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${fb.get('total_spend', 0):,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${fb.get('avg_cpi', 0):.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{fb.get('overall_roas', 0):.2f}</td>
                </tr>
                <tr style="background: #4285F4; color: white;">
                    <th style="padding: 8px;">Google Ads</th>
                    <th style="padding: 8px;">花费</th>
                    <th style="padding: 8px;">CPI</th>
                    <th style="padding: 8px;">ROAS</th>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">-</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${google.get('total_spend', 0):,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${google.get('avg_cpi', 0):.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{google.get('overall_roas', 0):.2f}</td>
                </tr>
                <tr style="background: #010101; color: white;">
                    <th style="padding: 8px;">TikTok Ads</th>
                    <th style="padding: 8px;">花费</th>
                    <th style="padding: 8px;">CPI</th>
                    <th style="padding: 8px;">ROAS</th>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">-</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${tiktok.get('total_spend', 0):,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${tiktok.get('avg_cpi', 0):.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{tiktok.get('overall_roas', 0):.2f}</td>
                </tr>
            </table>

            <h3>Campaign明细</h3>
            <table style="border-collapse: collapse; width: 100%;">
                <tr style="background: #333; color: white;">
                    <th style="padding: 8px;">Campaign</th>
                    <th style="padding: 8px;">平台</th>
                    <th style="padding: 8px;">花费</th>
                    <th style="padding: 8px;">安装</th>
                    <th style="padding: 8px;">CPI</th>
                    <th style="padding: 8px;">ROAS</th>
                </tr>
        """

        for camp in report.get("campaign_details", []):
            html += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">{camp['campaign_name']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{camp['platform']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${camp['spend']:,.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{camp['installs']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${camp['cpi']:.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{camp['roas']:.2f}</td>
                </tr>
            """

        html += """
            </table>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg.smtp_user
        msg["To"] = ", ".join(cfg.recipients)
        msg.attach(MIMEText(html, "html"))

        # Use SSL for port 465, STARTTLS for 587
        if cfg.smtp_port == 465:
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port)
            server.starttls()

        server.login(cfg.smtp_user, cfg.smtp_password)
        server.sendmail(cfg.smtp_user, cfg.recipients, msg.as_string())
        server.quit()

        logger.info(f"Email sent for {report_type} report to {cfg.recipients}")
        return True

    except Exception as e:
        logger.error(f"Email notification failed: {e}")
        return False
