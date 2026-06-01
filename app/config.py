"""Configuration management using Pydantic Settings + YAML."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class FeishuConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""


class EmailConfig(BaseModel):
    enabled: bool = False
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    recipients: list[str] = []


class NotificationsConfig(BaseModel):
    feishu: FeishuConfig = FeishuConfig()
    email: EmailConfig = EmailConfig()


class AppConfig(BaseModel):
    daily_spend_cap: float = 10000.0
    default_cpi_cap: float = 2.5
    default_roas_threshold: float = 1.2
    creative_fail_hours: int = 2
    budget_shift_ratio: float = 0.7
    use_mock: bool = True


class DatabaseConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///./data/auto_toufang.db"


class Settings(BaseSettings):
    app: AppConfig = AppConfig()
    database: DatabaseConfig = DatabaseConfig()
    notifications: NotificationsConfig = NotificationsConfig()

    model_config = {"env_prefix": "TOUFANG_", "env_nested_delimiter": "__"}


def load_settings(config_path: str | None = None) -> Settings:
    """Load settings from YAML file, then overlay environment variables."""
    if config_path is None:
        config_path = os.getenv("CONFIG_PATH", "config.yaml")

    path = Path(config_path)
    data = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    return Settings(**data)


# Global singleton
settings = load_settings()
