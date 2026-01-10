"""HTML page routes."""
import json
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from rss_glue.database import get_session
from rss_glue.models.db import Feed
from rss_glue.services.config_sync import get_current_config

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/")
def index(request: Request, session: Session = Depends(get_session)):
    """List all feeds."""
    feeds = list(session.exec(select(Feed)).all())
    return templates.TemplateResponse(
        "index.html", {"request": request, "feeds": feeds}
    )


@router.get("/config")
def config_page(request: Request, session: Session = Depends(get_session)):
    """Config editor page."""
    config = get_current_config(session)
    feeds_json = json.dumps(config["feeds"], indent=2)
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "config": config,
            "feeds_json": feeds_json,
            "error": None,
        },
    )
