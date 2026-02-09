"""Config API routes."""

import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session

from rss_glue.database import get_session
from rss_glue.models.config import AppConfig
from rss_glue.models.user import User
from rss_glue.services.auth import require_auth
from rss_glue.services.config_sync import get_current_config, sync_config_to_db
from rss_glue.templates import templates

router = APIRouter(include_in_schema=False)


@router.post("")
def save_config(
    request: Request,
    feeds_json: str = Form(...),
    cache_media: bool = Form(False),
    scrape_creators_key: str | None = Form(None),
    anthropic_api_key: str | None = Form(None),
    default_cooldown_minutes: int = Form(15),
    base_url: str = Form("http://localhost:8000"),
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
):
    """Save config and sync to database."""
    if scrape_creators_key == "":
        scrape_creators_key = None
    if anthropic_api_key == "":
        anthropic_api_key = None

    try:
        # Parse JSON
        feeds_list = json.loads(feeds_json)

        # Construct full config dict
        config_dict = {
            "cache_media": cache_media,
            "scrape_creators_key": scrape_creators_key,
            "anthropic_api_key": anthropic_api_key,
            "default_cooldown_minutes": default_cooldown_minutes,
            "base_url": base_url,
            "feeds": feeds_list,
        }

        # Validate with Pydantic
        app_config = AppConfig.model_validate(config_dict)

        # Sync to database
        sync_config_to_db(app_config, session)

        return RedirectResponse(url="/config", status_code=303)

    except json.JSONDecodeError as e:
        config_context = {
            "cache_media": cache_media,
            "scrape_creators_key": scrape_creators_key,
            "anthropic_api_key": anthropic_api_key,
            "default_cooldown_minutes": default_cooldown_minutes,
            "base_url": base_url,
            "feeds": [],
        }
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "config": config_context,
                "feeds_json": feeds_json,
                "error": f"Invalid JSON in feeds: {e}",
                "message": None,
                "password_error": None,
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
            "anthropic_api_key": anthropic_api_key,
            "default_cooldown_minutes": default_cooldown_minutes,
            "base_url": base_url,
            "feeds": feeds_list,
        }
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "config": config_context,
                "feeds_json": feeds_json,
                "error": str(e),
                "message": None,
                "password_error": None,
            },
            status_code=400,
        )


@router.post("/password")
def update_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
):
    """Update the current user's password."""
    config = get_current_config(session)
    feeds_json = json.dumps(config["feeds"], indent=2)

    # Helper to return error response
    def error_response(error: str):
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "config": config,
                "feeds_json": feeds_json,
                "error": None,
                "message": None,
                "password_error": error,
            },
            status_code=400,
        )

    # Verify current password
    if not user.verify_password(current_password):
        return error_response("Current password is incorrect")

    # Validate new password
    if len(new_password) < 8:
        return error_response("New password must be at least 8 characters")

    if new_password != confirm_password:
        return error_response("New passwords do not match")

    # Update password
    user.password_hash = User.hash_password(new_password)
    session.add(user)
    session.commit()

    # Redirect back to config with success message
    return RedirectResponse(
        url=f"/config?{urlencode({'message': 'Password updated successfully'})}",
        status_code=303,
    )
