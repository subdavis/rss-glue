"""Feed and update routes."""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import text as sql_text
from sqlmodel import Session, func, select

from rss_glue.database import get_session
from rss_glue.feeds import FeedRegistry
from rss_glue.models.db import Feed, Post, UpdateHistory
from rss_glue.models.user import User
from rss_glue.services.auth import require_auth
from rss_glue.services.background_worker import get_next_update
from rss_glue.services.config_sync import (
    get_base_url,
)
from rss_glue.services.media_cache import MEDIA_DIR, expand_placeholders
from rss_glue.services.rss_output import generate_rss
from rss_glue.services.update import reset_feed, update_feed
from rss_glue.templates import templates

router = APIRouter(include_in_schema=False)


def get_source_feed_ids(feed: Feed, session: Session) -> list[str]:
    """Get all source feed IDs for a feed.

    For merge feeds, recursively resolves all source feeds via tags.
    For other feeds, returns a list containing just the feed's own ID.
    """
    if feed.type != "merge":
        return [feed.id]

    return _resolve_merge_sources(feed.id, session)


def _resolve_merge_sources(merge_feed_id: str, session: Session) -> list[str]:
    """Recursively get all source feed IDs for a merge feed (using tags)."""
    from rss_glue.handlers.merge import get_merge_source_ids

    child_ids = get_merge_source_ids(merge_feed_id, session)

    result = []
    for child_id in child_ids:
        child_feed = session.get(Feed, child_id)
        if child_feed and child_feed.type == "merge":
            result.extend(_resolve_merge_sources(child_id, session))
        else:
            result.append(child_id)

    return result


@router.post("/feed/{feed_id}/update")
def trigger_update_feed(
    feed_id: str,
    force: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
):
    """Update a specific feed and redirect to HTML preview. Requires authentication."""
    try:
        feed = session.get(Feed, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

        result = update_feed(feed_id, session, force)
        if result:
            if result.status == "success":
                msg = f"Updated: {result.posts_added} posts added"
            else:
                msg = f"Update failed: {result.error_message}"
        else:
            # Feed was skipped - check why
            if not feed.enabled:
                msg = "Skipped: feed is disabled"
            else:
                msg = "Skipped: feed is on cooldown"
        return RedirectResponse(
            url=f"/feed/{feed_id}/html?message={msg}",
            status_code=303,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/feed/{feed_id}/reset")
def reset_feed_endpoint(
    feed_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
):
    """Reset a feed to its initial state and redirect to HTML preview. Requires authentication."""
    try:
        counts = reset_feed(feed_id, session)
        posts = counts.get("posts_deleted", 0)
        issues = counts.get("digest_issues_deleted", 0)
        files = counts.get("files_deleted", 0)
        items = posts + issues
        msg = f"Reset: {items} items, {files} files deleted"
        return RedirectResponse(
            url=f"/feed/{feed_id}/html?message={msg}",
            status_code=303,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/feed/{feed_id}/toggle")
def toggle_feed_endpoint(
    feed_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
):
    """Toggle the enabled state of a feed and redirect to HTML preview. Requires authentication."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    feed.enabled = not feed.enabled
    session.add(feed)
    session.commit()

    status = "enabled" if feed.enabled else "disabled"
    msg = f"Feed {status}"
    return RedirectResponse(
        url=f"/feed/{feed_id}/html?message={msg}",
        status_code=303,
    )


@router.get("/feed/{feed_id}/rss")
def get_feed_rss(
    feed_id: str,
    session: Session = Depends(get_session),
):
    """Get RSS output for a feed."""
    try:
        base_url = get_base_url(session)
        rss_xml = generate_rss(feed_id, session, base_url)
        return Response(content=rss_xml, media_type="application/rss+xml")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/feed/{feed_id}/html")
def get_feed_html(
    feed_id: str,
    request: Request,
    message: str | None = None,
    session: Session = Depends(get_session),
):
    """Get HTML preview for a feed."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    base_url = get_base_url(session)

    # Get handler and fetch posts using the standardized get_posts method
    handler = FeedRegistry.get_handler(feed.type)

    posts = handler.get_posts(feed_id, feed.limit, session, base_url)

    # Expand placeholders in post content and enclosure URLs for web display
    for post in posts:
        if post.get("content"):
            post["content"] = expand_placeholders(post["content"], base_url)
        for enc in post.get("enclosures", []):
            enc["url"] = expand_placeholders(enc["url"], base_url)

    next_update = get_next_update(feed, session)

    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "feed": feed,
            "posts": posts,
            "message": message,
            "next_update": next_update,
        },
    )


@router.get("/post/{feed_id}/{external_id}")
def get_post_permalink(
    feed_id: str,
    external_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Single-post page. Unauthenticated, matching /feed/{id}/rss."""
    post = session.exec(
        select(Post).where(Post.feed_id == feed_id, Post.external_id == external_id)
    ).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    base_url = get_base_url(session)
    response = templates.TemplateResponse(
        "post.html",
        {
            "request": request,
            "post": post,
            "feed": session.get(Feed, feed_id),
            "content": expand_placeholders(post.content or "", base_url),
        },
    )
    # This is the one page that renders third-party HTML bodies.
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; img-src * data:; media-src *; style-src 'self'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/media/{hash_prefix}/{filename}")
def serve_cached_media(hash_prefix: str, filename: str):
    """Serve cached media files.

    Args:
        hash_prefix: First 2 characters of the hash (directory name)
        filename: The hash-based filename with extension

    Returns:
        FileResponse with the cached media file
    """
    # Validate inputs to prevent path traversal
    if not hash_prefix.isalnum() or len(hash_prefix) != 2:
        raise HTTPException(status_code=400, detail="Invalid hash prefix")

    # Filename should start with the hash prefix
    if not filename.startswith(hash_prefix[:2]):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = MEDIA_DIR / hash_prefix / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Media file not found")

    # Verify the path is still within MEDIA_DIR (security check)
    try:
        file_path.resolve().relative_to(MEDIA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    return FileResponse(file_path)


@router.get("/update-history")
def get_update_history(
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    """Get paginated update history for all feeds."""
    return _render_update_history(request, session, page, feed=None, new_only=False)


@router.get("/update-history/new")
def get_update_history_new(
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    """Get paginated update history for all feeds, showing only updates with new posts."""
    return _render_update_history(request, session, page, feed=None, new_only=True)


@router.get("/feed/{feed_id}/history")
def get_feed_history(
    feed_id: str,
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    """Get paginated update history for a specific feed."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")
    return _render_update_history(request, session, page, feed=feed, new_only=False)


@router.get("/feed/{feed_id}/history/new")
def get_feed_history_new(
    feed_id: str,
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    """Get paginated update history for a specific feed, showing only updates with new posts."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")
    return _render_update_history(request, session, page, feed=feed, new_only=True)


def _render_update_history(
    request: Request,
    session: Session,
    page: int,
    feed: Feed | None,
    new_only: bool = False,
):
    """Render update history page for all feeds or a specific feed.

    For merge feeds, shows history from all source feeds.
    """
    if page < 1:
        page = 1

    records_per_page = 100
    offset = (page - 1) * records_per_page

    # Build query with optional feed filter
    count_query = select(func.count(UpdateHistory.id))
    history_query = (
        select(UpdateHistory, Feed)
        .join(Feed, UpdateHistory.feed_id == Feed.id)  # type: ignore[arg-type]
        .order_by(UpdateHistory.started_at.desc())  # type: ignore[union-attr]
    )

    if feed:
        # For merge feeds, get history from all source feeds
        source_ids = get_source_feed_ids(feed, session)
        count_query = count_query.where(UpdateHistory.feed_id.in_(source_ids))  # type: ignore[union-attr]
        history_query = history_query.where(UpdateHistory.feed_id.in_(source_ids))  # type: ignore[union-attr]

    if new_only:
        count_query = count_query.where(UpdateHistory.posts_added > 0)
        history_query = history_query.where(UpdateHistory.posts_added > 0)

    total_count = session.exec(count_query).first() or 0
    total_pages = (total_count + records_per_page - 1) // records_per_page

    history_records = session.exec(
        history_query.offset(offset).limit(records_per_page)
    ).all()

    # Convert to list of dictionaries for template
    history_data = []
    for history, history_feed in history_records:
        history_data.append(
            {
                "history": history,
                "feed": history_feed,
            }
        )

    # Determine pagination base URL
    base_path = f"/feed/{feed.id}/history" if feed else "/update-history"
    pagination_base_url = f"{base_path}/new" if new_only else base_path

    next_update = get_next_update(feed, session) if feed else None
    worker_enabled = os.getenv("ENABLE_BACKGROUND_WORKER", "").lower() in (
        "true",
        "1",
        "yes",
    )
    return templates.TemplateResponse(
        "update_history.html",
        {
            "request": request,
            "feed": feed,
            "next_update": next_update,
            "worker_enabled": worker_enabled,
            "history_data": history_data,
            "pagination_base_url": pagination_base_url,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
            "active_tab": "new" if new_only else "all",
            "base_path": base_path,
        },
    )


@router.get("/feed/{feed_id}/gallery")
def get_feed_gallery(
    feed_id: str,
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    """Get gallery of images for a specific feed.

    For merge feeds, shows images from all source feeds.
    """
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    if page < 1:
        page = 1

    images_per_page = 50
    offset = (page - 1) * images_per_page

    # Get source feed IDs (handles merge feeds)
    source_ids = get_source_feed_ids(feed, session)

    # Build placeholders for SQL IN clause
    placeholders = ", ".join(f":feed_id_{i}" for i in range(len(source_ids)))
    params = {f"feed_id_{i}": fid for i, fid in enumerate(source_ids)}
    params["limit"] = images_per_page
    params["offset"] = offset

    # Query for images from the feed(s)
    union_query = sql_text(f"""
        SELECT local_path, post_id, feed_id, published_at, COUNT(*) OVER() as total_count
        FROM (
            SELECT mc.local_path, mc.post_id, mc.feed_id, p.published_at
            FROM media_cache mc
            JOIN post p ON mc.post_id = p.id
            WHERE mc.content_type LIKE 'image/%' AND mc.feed_id IN ({placeholders})
            UNION ALL
            SELECT e.local_path, e.post_id, p.feed_id, p.published_at
            FROM enclosure e
            JOIN post p ON e.post_id = p.id
            WHERE e.local_path IS NOT NULL AND e.mime_type LIKE 'image/%' AND p.feed_id IN ({placeholders})
        )
        ORDER BY published_at DESC
        LIMIT :limit OFFSET :offset
    """)

    results = session.exec(union_query, params=params).all()

    # Extract total count from first row (or 0 if no results)
    total_count = results[0][4] if results else 0
    total_pages = (total_count + images_per_page - 1) // images_per_page

    # Build gallery data from results
    gallery_data = []
    for row in results:
        local_path, post_id, row_feed_id, _, _ = row
        post = session.get(Post, post_id)
        row_feed = session.get(Feed, row_feed_id)

        if post and local_path and row_feed:
            path_parts = local_path.split("/")
            if len(path_parts) >= 2:
                media_url = f"/media/{path_parts[-2]}/{path_parts[-1]}"
            else:
                media_url = f"/media/{local_path}"
            gallery_data.append(
                {
                    "feed": row_feed,
                    "post": post,
                    "media_url": media_url,
                }
            )

    next_update = get_next_update(feed, session)
    return templates.TemplateResponse(
        "gallery.html",
        {
            "request": request,
            "feed": feed,
            "next_update": next_update,
            "gallery_data": gallery_data,
            "pagination_base_url": f"/feed/{feed_id}/gallery",
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    )
