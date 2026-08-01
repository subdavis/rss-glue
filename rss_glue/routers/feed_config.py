"""Feed configuration routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from rss_glue.database import get_session
from rss_glue.feeds import FeedRegistry
from rss_glue.models.db import Feed
from rss_glue.models.user import User
from rss_glue.services.auth import require_admin_auth
from rss_glue.models.feed_config import DEFAULT_STRIP_TAGS
from rss_glue.services.config_sync import (
    get_global_cache_media,
    get_global_cooldown,
    upsert_feed,
)
from rss_glue.templates import templates

router = APIRouter(include_in_schema=False)


def _feed_config_context(
    feed_type: str,
    session: Session,
    feed: Feed | None = None,
    form_values: dict | None = None,
    errors: dict | None = None,
) -> dict:
    """Build template context for the feed config/new form."""
    global_cooldown = get_global_cooldown(session)
    global_cache_media = get_global_cache_media(session)
    handler_cls = FeedRegistry.get_handler(feed_type)
    all_feeds = (
        list(session.exec(select(Feed)).all())
        if "source" in handler_cls.Config.model_fields
        else []
    )
    return {
        "feed": feed,
        "feed_type": feed_type,
        "form_values": form_values or {},
        "errors": errors or {},
        "global_cooldown": global_cooldown,
        "global_cache_media": global_cache_media,
        "all_feeds": all_feeds,
        **handler_cls.config_form_context(session),
    }


@router.get("/feed/{feed_id}/config")
def feed_config_page(
    feed_id: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Render the config form for an existing feed."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    handler_cls = FeedRegistry.get_handler(feed.type)
    hydrated = handler_cls.Config.db_hydrate(feed, session=session, **feed.config)
    form_values = hydrated.model_dump(exclude_none=False)
    # Normalize list fields for text inputs
    form_values["tags"] = ", ".join(form_values.get("tags") or [])
    form_values["strip_tags"] = ", ".join(form_values.get("strip_tags") or [])

    ctx = _feed_config_context(feed.type, session, feed=feed, form_values=form_values)
    return templates.TemplateResponse("feed_config.html", {"request": request, **ctx})


@router.post("/feed/{feed_id}/config")
async def feed_config_save(
    feed_id: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Save config for an existing feed."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    form = await request.form()
    form_data = dict(form)

    saved, errors = upsert_feed(form_data, session, existing_feed_id=feed_id)
    if errors:
        ctx = _feed_config_context(
            feed.type, session, feed=feed, form_values=form_data, errors=errors
        )
        return templates.TemplateResponse(
            "feed_config.html", {"request": request, **ctx}, status_code=400
        )

    return RedirectResponse(
        url=f"/feed/{feed_id}/config?message=Saved", status_code=303
    )


@router.post("/feed/{feed_id}/delete")
def feed_delete(
    feed_id: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Delete a feed and all associated data."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    session.delete(feed)
    session.commit()
    return RedirectResponse(url="/config?message=Feed+deleted", status_code=303)


@router.get("/new_feed/{feed_type}")
def feed_new_page(
    feed_type: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Render the creation form for a new feed of the given type."""
    try:
        FeedRegistry.get_handler(feed_type)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown feed type: {feed_type!r}")

    ctx = _feed_config_context(
        feed_type,
        session,
        form_values={
            "type": feed_type,
            "strip_tags": ", ".join(DEFAULT_STRIP_TAGS),
        },
    )
    return templates.TemplateResponse("feed_config.html", {"request": request, **ctx})


@router.post("/new_feed/{feed_type}")
async def feed_new_save(
    feed_type: str,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_admin_auth),
):
    """Create a new feed of the given type."""
    try:
        FeedRegistry.get_handler(feed_type)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown feed type: {feed_type!r}")

    form = await request.form()
    form_data = dict(form)
    form_data["type"] = feed_type

    saved, errors = upsert_feed(form_data, session)
    if errors:
        ctx = _feed_config_context(
            feed_type, session, form_values=form_data, errors=errors
        )
        return templates.TemplateResponse(
            "feed_config.html", {"request": request, **ctx}, status_code=400
        )

    assert saved is not None
    return RedirectResponse(
        url=f"/feed/{saved.id}/config?message=Feed+created", status_code=303
    )
