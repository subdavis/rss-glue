"""HTML page routes."""

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select, func

from rss_glue.database import get_session
from rss_glue.models.db import Feed, Post
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
    from sqlalchemy import text as sql_text

    if page < 1:
        page = 1

    images_per_page = 50
    offset = (page - 1) * images_per_page

    # Use UNION ALL with COUNT(*) OVER() to get total count and paginated results in one query
    union_query = sql_text("""
        SELECT local_path, post_id, feed_id, published_at, COUNT(*) OVER() as total_count
        FROM (
            SELECT mc.local_path, mc.post_id, mc.feed_id, p.published_at
            FROM media_cache mc
            JOIN post p ON mc.post_id = p.id
            WHERE mc.content_type LIKE 'image/%'
            UNION ALL
            SELECT e.local_path, e.post_id, p.feed_id, p.published_at
            FROM enclosure e
            JOIN post p ON e.post_id = p.id
            WHERE e.local_path IS NOT NULL AND e.mime_type LIKE 'image/%'
        )
        ORDER BY published_at DESC
        LIMIT :limit OFFSET :offset
    """)

    results = session.exec(union_query, params={"limit": images_per_page, "offset": offset}).all()

    # Extract total count from first row (or 0 if no results)
    total_count = results[0][4] if results else 0
    total_pages = (total_count + images_per_page - 1) // images_per_page

    # Build gallery data from results
    gallery_data = []
    for row in results:
        # Row is a tuple: (local_path, post_id, feed_id, published_at, total_count)
        local_path, post_id, feed_id, _, _ = row

        # Get feed and post objects
        feed = session.get(Feed, feed_id)
        post = session.get(Post, post_id)

        if feed and post and local_path:
            path_parts = local_path.split("/")
            if len(path_parts) >= 2:
                media_url = f"/media/{path_parts[-2]}/{path_parts[-1]}"
            else:
                media_url = f"/media/{local_path}"
            gallery_data.append({
                "feed": feed,
                "post": post,
                "media_url": media_url,
            })

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
