"""Feed and update routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlmodel import Session, select, func

from rss_glue.database import get_session
from rss_glue.models.db import Feed, UpdateHistory
from rss_glue.models.user import User
from rss_glue.services.auth import require_auth
from rss_glue.services.config_sync import get_current_config
from rss_glue.services.media_cache import MEDIA_DIR, expand_placeholders
from rss_glue.services.rss_output import generate_rss
from rss_glue.services.update import reset_feed, update_all_feeds, update_feed
from rss_glue.templates import templates

router = APIRouter()


@router.post("/update")
def trigger_update_all(
    force: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(require_auth),
):
    """Update all feeds in topological order. Requires authentication."""
    results = update_all_feeds(session, force)
    return {
        "updated": len(results),
        "results": [
            {
                "feed_id": r.feed_id,
                "status": r.status,
                "posts_added": r.posts_added,
                "error": r.error_message,
            }
            for r in results
        ],
    }


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
        config = get_current_config(session)
        base_url = config["base_url"]
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

    from rss_glue.feeds.registry import FeedRegistry

    config = get_current_config(session)
    base_url = config["base_url"]

    # Get handler and fetch posts using the standardized get_posts method
    handler = FeedRegistry.get_handler(feed.type)
    posts = handler.get_posts(feed_id, feed.limit, session, base_url)

    # Expand placeholders in post content and enclosure URLs for web display
    for post in posts:
        if post.get("content"):
            post["content"] = expand_placeholders(post["content"], base_url)
        for enc in post.get("enclosures", []):
            enc["url"] = expand_placeholders(enc["url"], base_url)

    return templates.TemplateResponse(
        "feed.html",
        {"request": request, "feed": feed, "posts": posts, "message": message},
    )


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
    """Get paginated update history."""
    if page < 1:
        page = 1

    records_per_page = 100
    offset = (page - 1) * records_per_page

    # Get total count for pagination
    total_count = session.exec(select(func.count(UpdateHistory.id))).first() or 0
    total_pages = (total_count + records_per_page - 1) // records_per_page

    # Get paginated records in reverse chronological order
    history_records = session.exec(
        select(UpdateHistory, Feed)
        .join(Feed, UpdateHistory.feed_id == Feed.id)
        .order_by(UpdateHistory.started_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(records_per_page)
    ).all()

    # Convert to list of dictionaries for template
    history_data = []
    for history, feed in history_records:
        history_data.append(
            {
                "history": history,
                "feed": feed,
            }
        )

    return templates.TemplateResponse(
        "update_history.html",
        {
            "request": request,
            "history_data": history_data,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        },
    )
