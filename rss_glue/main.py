"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rss_glue.database import create_db_and_tables
from rss_glue.routers import pages, config, feeds

# Import feeds module to register handlers
import rss_glue.feeds  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    create_db_and_tables()
    yield
    # Shutdown


app = FastAPI(title="RSS Glue v2", lifespan=lifespan)

# Include routers
app.include_router(pages.router)
app.include_router(config.router, prefix="/config", tags=["config"])
app.include_router(feeds.router, tags=["feeds"])
