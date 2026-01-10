"""Feed and update routes."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from rss_glue.database import get_session
from rss_glue.models.db import Feed, Post
from rss_glue.services.update import update_all_feeds, update_feed
from rss_glue.services.rss_output import generate_rss
from rss_glue.services.media_cache import MEDIA_DIR

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.post("/update")
def trigger_update_all(
    request: Request,
    session: Session = Depends(get_session),
):
    """Update all feeds in topological order."""
    base_url = str(request.base_url)
    results = update_all_feeds(session, base_url)
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
    request: Request,
    session: Session = Depends(get_session),
):
    """Update a specific feed."""
    try:
        base_url = str(request.base_url)
        result = update_feed(feed_id, session, base_url)
        return {
            "feed_id": result.feed_id,
            "status": result.status,
            "posts_added": result.posts_added,
            "error": result.error_message,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/feed/{feed_id}/rss")
def get_feed_rss(
    feed_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Get RSS output for a feed."""
    try:
        base_url = str(request.base_url)
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

    from rss_glue.feeds.merge import MergeFeedHandler
    from rss_glue.feeds.digest import DigestFeedHandler
    from rss_glue.services.rss_output import format_digest_issue_content

    posts = []
    if feed.type == "merge":
        posts = MergeFeedHandler.get_merged_posts(feed_id, feed.limit, session)
    elif feed.type == "digest":
        issues = DigestFeedHandler.get_digest_issues(feed_id, feed.limit, session)
        base_url = str(request.base_url)
        
        # Convert issues to post-like objects for template
        for issue in issues:
            issue_posts = DigestFeedHandler.get_issue_posts(issue.id, session)
            content = format_digest_issue_content(issue_posts, base_url)
            
            start_str = issue.period_start.strftime("%b %d")
            end_str = issue.period_end.strftime("%b %d, %Y")
            
            posts.append({
                "title": f"{feed.name}: {start_str} - {end_str}",
                "link": f"{base_url}feed/{feed_id}/rss",
                "published_at": issue.period_end,
                "content": content,
                "author": "System"
            })
    else:
        posts = list(
            session.exec(
                select(Post)
                .where(Post.feed_id == feed_id)
                .order_by(Post.published_at.desc())
            ).all()
        )

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
