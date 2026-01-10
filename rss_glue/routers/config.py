"""Config API routes."""
import json
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from pydantic import ValidationError

from rss_glue.database import get_session
from rss_glue.models.config import AppConfig
from rss_glue.services.config_sync import sync_config_to_db

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.post("")
def save_config(
    request: Request,
    feeds_json: str = Form(...),
    cache_media: bool = Form(False),
    scrape_creators_key: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Save config and sync to database."""
    if scrape_creators_key == "":
        scrape_creators_key = None

    try:
        # Parse JSON
        feeds_list = json.loads(feeds_json)

        # Construct full config dict
        config_dict = {
            "cache_media": cache_media,
            "scrape_creators_key": scrape_creators_key,
            "feeds": feeds_list,
        }

        # Validate with Pydantic
        app_config = AppConfig(**config_dict)

        # Sync to database
        sync_config_to_db(app_config, session)

        return RedirectResponse(url="/", status_code=303)

    except json.JSONDecodeError as e:
        config_context = {
            "cache_media": cache_media,
            "scrape_creators_key": scrape_creators_key,
            "feeds": [],
        }
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "config": config_context,
                "feeds_json": feeds_json,
                "error": f"Invalid JSON in feeds: {e}",
            },
            status_code=400,
        )
    except ValidationError as e:
        try:
            feeds_list = json.loads(feeds_json)
        except Exception:
            feeds_list = []

        config_context = {
            "cache_media": cache_media,
            "scrape_creators_key": scrape_creators_key,
            "feeds": feeds_list,
        }
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "config": config_context,
                "feeds_json": feeds_json,
                "error": str(e),
            },
            status_code=400,
        )
