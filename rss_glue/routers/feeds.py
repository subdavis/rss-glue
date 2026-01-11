"""Feed and update routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from rss_glue.database import get_session
from rss_glue.models.db import Feed, Post, UpdateHistory
from rss_glue.services.config_sync import get_current_config
from rss_glue.services.media_cache import MEDIA_DIR, expand_placeholders
from rss_glue.services.rss_output import generate_rss
from rss_glue.services.update import reset_feed, update_all_feeds, update_feed

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.post("/update")
def trigger_update_all(
    force: bool = False,
    session: Session = Depends(get_session),
):
    """Update all feeds in topological order."""
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
):
    """Update a specific feed."""
    try:
        result = update_feed(feed_id, session, force)
        if result:
            return {
                "feed_id": result.feed_id,
                "status": result.status,
                "posts_added": result.posts_added,
                "error": result.error_message,
            }
        else:
            return {
                "feed_id": feed_id,
                "status": "skipped",
            }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/feed/{feed_id}/reset")
def reset_feed_endpoint(
    feed_id: str,
    session: Session = Depends(get_session),
):
    """Reset a feed to its initial state.

    Removes posts, media cache, update history, and physical media files.
    For derivative feeds (merge/digest), does not affect source feeds.
    """
    try:
        counts = reset_feed(feed_id, session)
        return {
            "feed_id": feed_id,
            "status": "reset",
            **counts,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
    session: Session = Depends(get_session),
):
    """Get HTML preview for a feed."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    from rss_glue.feeds.digest import DigestFeedHandler
    from rss_glue.feeds.merge import MergeFeedHandler
    from rss_glue.services.rss_output import format_digest_issue_content

    posts = []
    if feed.type == "merge":
        posts = MergeFeedHandler.get_merged_posts(feed_id, feed.limit, session)
    elif feed.type == "digest":
        issues = DigestFeedHandler.get_digest_issues(feed_id, feed.limit, session)
        config = get_current_config(session)
        base_url = config["base_url"]

        # Convert issues to post-like objects for template
        for issue in issues:
            if issue.id is None:
                continue
            issue_posts = DigestFeedHandler.get_issue_posts(issue.id, session)
            content = format_digest_issue_content(issue_posts, base_url)

            start_str = issue.period_start.strftime("%b %d")
            end_str = issue.period_end.strftime("%b %d, %Y")

            posts.append(
                {
                    "title": f"{feed.name}: {start_str} - {end_str}",
                    "link": f"{base_url}feed/{feed_id}/rss",
                    "published_at": issue.period_end,
                    "content": content,
                    "author": "System",
                }
            )
    else:
        posts = list(
            session.exec(
                select(Post)
                .where(Post.feed_id == feed_id)
                .order_by(Post.published_at.desc())  # type: ignore[union-attr]
            ).all()
        )

    # Expand placeholders in post content for web display
    config = get_current_config(session)
    base_url = config["base_url"]
    for post in posts:
        if hasattr(post, "content") and post.content:
            post.content = expand_placeholders(post.content, base_url)

    return templates.TemplateResponse(
        "feed.html", {"request": request, "feed": feed, "posts": posts}
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
