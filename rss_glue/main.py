"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Import feeds module to register handlers
import rss_glue.feeds  # noqa: F401

# Import User model to register with SQLModel before table creation
import rss_glue.models.user  # noqa: F401
from rss_glue.database import create_db_and_tables
from rss_glue.routers import api, auth, global_config, feeds, feed_config, pages
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
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(global_config.router, prefix="/config", tags=["config"])
app.include_router(feeds.router, tags=["feeds"])
app.include_router(feed_config.router, tags=["feeds"])
app.include_router(api.router, prefix="/api", tags=["api"])

# Mount static files (CSS, etc.)
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
