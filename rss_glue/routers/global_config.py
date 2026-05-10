"""Config API routes."""

from rss_glue.feeds import FeedRegistry

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from rss_glue.database import get_session
from rss_glue.models.user import User
from rss_glue.services.auth import (
    get_or_create_api_key,
    regenerate_api_key,
    require_admin_auth,
)
from rss_glue.services.config_sync import get_current_config, save_system_config
from rss_glue.templates import templates

router = APIRouter(include_in_schema=False)


def _config_template(
    request: Request,
    session: Session,
    *,
    error: str | None = None,
    message: str | None = None,
    password_error: str | None = None,
):
    config = get_current_config(session)
    feed_types = FeedRegistry.supported_types()
    api_key = get_or_create_api_key(session)

    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "config": config,
            "error": error,
            "feed_types": feed_types,
            "message": message,
            "password_error": password_error,
            "api_key": api_key,
        },
        status_code=400 if (error or password_error) else 200,
    )


@router.get("")
def config_page(
    request: Request,
    message: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    return _config_template(request, session, message=message)


@router.post("")
def save_config(
    request: Request,
    cache_media: bool = Form(False),
    scrape_creators_key: str | None = Form(None),
    anthropic_api_key: str | None = Form(None),
    default_cooldown_minutes: int = Form(15),
    base_url: str = Form("http://localhost:8000"),
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Save global settings."""
    save_system_config("cache_media", str(cache_media).lower(), session)
    save_system_config("scrape_creators_key", scrape_creators_key or None, session)
    save_system_config("anthropic_api_key", anthropic_api_key or None, session)
    save_system_config(
        "default_cooldown_minutes", str(default_cooldown_minutes), session
    )
    save_system_config("base_url", base_url, session)
    session.commit()
    return RedirectResponse(url="/config?message=Settings+saved", status_code=303)


@router.post("/password")
def update_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Update the current user's password."""
    if not user.verify_password(current_password):
        return _config_template(
            request, session, password_error="Current password is incorrect"
        )

    if len(new_password) < 8:
        return _config_template(
            request,
            session,
            password_error="New password must be at least 8 characters",
        )

    if new_password != confirm_password:
        return _config_template(
            request, session, password_error="New passwords do not match"
        )

    user.password_hash = User.hash_password(new_password)
    session.add(user)
    session.commit()

    return RedirectResponse(
        url=f"/config?{urlencode({'message': 'Password updated successfully'})}",
        status_code=303,
    )


@router.post("/api-key/regenerate")
def regenerate_api_key_endpoint(
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Regenerate the API key."""
    regenerate_api_key(session)
    return RedirectResponse(
        url=f"/config?{urlencode({'message': 'API key regenerated'})}",
        status_code=303,
    )
