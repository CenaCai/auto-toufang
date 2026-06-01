"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    # Init database
    await init_db()
    logger.info("Database initialized")

    # Start scheduler
    start_scheduler()

    yield

    # Shutdown
    stop_scheduler()


app = FastAPI(
    title="Auto投放",
    description="Facebook & Google Ads 自动化投放管理系统",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
from app.routers.api import router as api_router
from app.routers.dashboard import router as dashboard_router

app.include_router(api_router)
app.include_router(dashboard_router)
