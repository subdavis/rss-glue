"""JSON API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from rss_glue.database import get_session
from rss_glue.models.db import Feed, Post
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
    if feed_id:
        feed = session.get(Feed, feed_id)
        if not feed:
            raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    query = select(Post).order_by(Post.published_at.desc()).limit(limit)  # type: ignore[union-attr]
    if feed_id:
        query = query.where(Post.feed_id == feed_id)
    posts = session.exec(query).all()

    config = get_current_config(session)
    base_url = config["base_url"]

    return [
        {
            "id": post.id,
            "feed_id": post.feed_id,
            "external_id": post.external_id,
            "title": post.title,
            "link": post.link,
            "author": post.author,
            "published_at": post.published_at.isoformat(),
            "content": expand_placeholders(post.content, base_url) if post.content else None,
        }
        for post in posts
    ]


SENSITIVE_CONFIG_KEYS = {"scrape_creators_key"}


@router.get("/config")
def get_config(session: Session = Depends(get_session)):
    """Get current configuration (excluding sensitive values)."""
    config = get_current_config(session)
    return {k: v for k, v in config.items() if k not in SENSITIVE_CONFIG_KEYS}
