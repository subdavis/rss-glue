"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Import feeds module to register handlers
import rss_glue.feeds  # noqa: F401
from rss_glue.database import create_db_and_tables
from rss_glue.routers import config, feeds, pages
from rss_glue.services.background_worker import (
    start_background_worker,
    stop_background_worker,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    create_db_and_tables()
    await start_background_worker()
    yield
    # Shutdown
    await stop_background_worker()


app = FastAPI(title="RSS Glue v2", lifespan=lifespan)

# Include routers
app.include_router(pages.router)
app.include_router(config.router, prefix="/config", tags=["config"])
app.include_router(feeds.router, tags=["feeds"])
