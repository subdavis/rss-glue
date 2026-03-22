"""JSON API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from rss_glue.database import get_session
from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import Feed
from rss_glue.services.config_sync import get_current_config
from rss_glue.services.media_cache import expand_placeholders

router = APIRouter()


@router.get("/feeds")
def list_feeds(session: Session = Depends(get_session)):
    """List all feeds."""
    feeds = session.exec(select(Feed)).all()
    return [
        {
            "id": feed.id,
            "type": feed.type,
            "name": feed.name,
            "limit": feed.limit,
            "enabled": feed.enabled,
            "tags": [t.name for t in feed.tags],
            "updated_at": feed.updated_at.isoformat() if feed.updated_at else None,
        }
        for feed in feeds
    ]


@router.get("/posts")
def list_posts(
    feed_id: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    """List posts, optionally filtered by feed."""
    if not feed_id:
        raise HTTPException(status_code=400, detail="feed_id is required")

    feed = session.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    config = get_current_config(session)
    base_url = config["base_url"]

    handler = FeedRegistry.get_handler(feed.type)
    posts = handler.get_posts(feed_id, limit, session, base_url)

    return [
        {
            "id": post["id"],
            "title": post["title"],
            "link": post["link"],
            "author": post.get("author"),
            "published_at": post["published_at"].isoformat(),
            "content": expand_placeholders(post["content"], base_url)
            if post.get("content")
            else None,
            **({"metadata": post["metadata"]} if post.get("metadata") else {}),
        }
        for post in posts
    ]
