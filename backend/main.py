"""
FRIDAY — Main FastAPI Application

Entry point for the backend server.
"""

import logging
import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database.database import init_db
from scheduler.jobs import start_scheduler, stop_scheduler, run_maintenance
from api.webhook import router as webhook_router
from api.events import router as events_router

settings = get_settings()

# ─── Logging Setup ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Lifespan ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("🚀 FRIDAY backend starting...")

    # Initialize database tables
    await init_db()
    logger.info("✅ Database initialized")

    # Start scheduler
    start_scheduler()

    yield  # App runs here

    # Shutdown
    stop_scheduler()
    logger.info("👋 FRIDAY backend stopped.")


# ─── App ───────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FRIDAY — AI WhatsApp Secretary",
    description="Backend for FRIDAY: an AI personal secretary that lives in WhatsApp.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(webhook_router)
app.include_router(events_router)


@app.get("/")
async def root():
    return {
        "name": "FRIDAY",
        "status": "running",
        "description": "AI WhatsApp Secretary — Backend API",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/maintenance", include_in_schema=False)
async def maintenance(x_cron_secret: str = Header(default="")):
    """Protected wake-up endpoint used by GitHub Actions on free hosting."""
    if not settings.cron_secret or not hmac.compare_digest(
        x_cron_secret, settings.cron_secret
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await run_maintenance()
