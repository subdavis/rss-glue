"""HTML page routes."""

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select, func

from rss_glue.database import get_session
from rss_glue.models.db import Feed, MediaCache, Post
from rss_glue.models.user import User
from rss_glue.services.auth import get_current_user_optional, require_auth
from rss_glue.services.config_sync import get_current_config
from rss_glue.services.background_worker import get_next_update
from rss_glue.templates import templates

router = APIRouter()


@router.get("/")
def index(
    request: Request,
    sort_by: str = "name",
    sort_order: str = "asc",
    session: Session = Depends(get_session),
):
    """List all feeds with optional sorting."""
    feeds = list(session.exec(select(Feed)).all())

    # Calculate next update time for each feed
    feed_schedules = []
    for feed in feeds:
        next_update = get_next_update(feed, session)
        feed_schedules.append({
            "feed": feed,
            "next_update": next_update,
        })

    # Sort feed_schedules based on sort_by parameter
    def get_sort_key(item):
        feed = item["feed"]
        if sort_by == "name":
            return feed.name.lower()
        elif sort_by == "type":
            return feed.type
        elif sort_by == "limit":
            return feed.limit
        elif sort_by == "status":
            return feed.enabled
        elif sort_by == "updated_at":
            # Handle None values by putting them at the end
            return feed.updated_at or (
                datetime.min.replace(tzinfo=timezone.utc)
                if sort_order == "asc"
                else datetime.max.replace(tzinfo=timezone.utc)
            )
        elif sort_by == "next_update":
            # Handle None values by putting them at the end
            return item["next_update"] or (
                datetime.min.replace(tzinfo=timezone.utc)
                if sort_order == "asc"
                else datetime.max.replace(tzinfo=timezone.utc)
            )
        return feed.name.lower()  # Default to name

    feed_schedules.sort(key=get_sort_key, reverse=(sort_order == "desc"))

    # Check if worker is enabled
    worker_enabled = os.getenv("ENABLE_BACKGROUND_WORKER", "").lower() in (
        "true",
        "1",
        "yes",
    )

    # Get current time for overdue check
    now = datetime.now(timezone.utc)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "feed_schedules": feed_schedules,
            "worker_enabled": worker_enabled,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "now": now,
        },
    )


@router.get("/config")
def config_page(
    request: Request,
    message: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
):
    """Config editor page. Requires authentication."""
    config = get_current_config(session)
    feeds_json = json.dumps(config["feeds"], indent=2)
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "config": config,
            "feeds_json": feeds_json,
            "error": None,
            "message": message,
            "password_error": None,
        },
    )


@router.get("/gallery")
def gallery_page(
    request: Request, page: int = 1, session: Session = Depends(get_session)
):
    """Gallery page showing all media images in reverse chronological order."""
    if page < 1:
        page = 1

    images_per_page = 50
    offset = (page - 1) * images_per_page

    # Get total count for pagination (only images)
    total_count = (
        session.exec(
            select(func.count(MediaCache.id)).where(
                MediaCache.content_type.like("image/%")
            )
        ).first()
        or 0
    )
    total_pages = (total_count + images_per_page - 1) // images_per_page

    # Get paginated media records in reverse chronological order by post published time
    media_records = session.exec(
        select(MediaCache, Feed, Post)
        .join(Feed, MediaCache.feed_id == Feed.id)
        .join(Post, MediaCache.post_id == Post.id)
        .where(MediaCache.content_type.like("image/%"))  # Only images
        .order_by(Post.published_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(images_per_page)
    ).all()

    # Convert to list of dictionaries for template
    gallery_data = []
    for media, feed, post in media_records:
        # Build media URL from local_path
        # Format: /media/{hash_prefix}/{filename}
        path_parts = media.local_path.split("/")
        if len(path_parts) >= 2:
            hash_prefix = path_parts[-2]
            filename = path_parts[-1]
            media_url = f"/media/{hash_prefix}/{filename}"
        else:
            # Fallback if path format is unexpected
            media_url = f"/media/{media.local_path}"

        gallery_data.append(
            {"media": media, "feed": feed, "post": post, "media_url": media_url}
        )

    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "gallery_data": gallery_data,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    )


@router.get("/posts")
def posts_page(
    request: Request, page: int = 1, session: Session = Depends(get_session)
):
    """Posts page showing all source posts in reverse chronological order."""
    if page < 1:
        page = 1

    posts_per_page = 50
    offset = (page - 1) * posts_per_page

    # Get total count for pagination (only source posts, not merge/digest)
    total_count = (
        session.exec(
            select(func.count(Post.id))
            .join(Feed, Post.feed_id == Feed.id)
            .where(Feed.type.not_in(["merge", "digest"]))
        ).first()
        or 0
    )
    total_pages = (total_count + posts_per_page - 1) // posts_per_page

    # Get paginated posts in reverse chronological order
    post_records = session.exec(
        select(Post, Feed)
        .join(Feed, Post.feed_id == Feed.id)
        .where(Feed.type.not_in(["merge", "digest"]))
        .order_by(Post.published_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(posts_per_page)
    ).all()

    # Convert to list of dictionaries for template
    posts_data = []
    for post, feed in post_records:
        posts_data.append({"post": post, "feed": feed})

    return templates.TemplateResponse(
        "posts.html",
        {
            "request": request,
            "posts_data": posts_data,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    )
