"""Config API routes."""

from rss_glue.feeds import FeedRegistry

import logging
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

logger = logging.getLogger(__name__)

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
    imap_host: str = Form(""),
    imap_port: int = Form(993),
    imap_user: str = Form(""),
    imap_password: str | None = Form(None),
    imap_folder: str = Form("INBOX"),
    imap_lookback_days: int = Form(7),
    imap_max_message_bytes: int = Form(2 * 1024 * 1024),
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
    save_system_config("imap_host", imap_host.strip(), session)
    save_system_config("imap_port", str(imap_port), session)
    save_system_config("imap_user", imap_user.strip(), session)
    # Blank password means "leave it alone", so the form can round-trip safely.
    save_system_config("imap_password", imap_password or None, session)
    save_system_config("imap_folder", imap_folder.strip() or "INBOX", session)
    save_system_config("imap_lookback_days", str(imap_lookback_days), session)
    save_system_config("imap_max_message_bytes", str(imap_max_message_bytes), session)
    session.commit()
    return RedirectResponse(url="/config?message=Settings+saved", status_code=303)


@router.post("/imap/test")
def test_imap_connection(
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Connect to the configured inbox and report what we can see."""
    from rss_glue.services import imap_inbox

    try:
        message = imap_inbox.test_connection(session)
    except Exception as e:
        logger.exception("IMAP test connection failed")
        message = f"IMAP test failed: {type(e).__name__}: {e}"
    return RedirectResponse(
        url=f"/config?{urlencode({'message': message})}", status_code=303
    )


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
