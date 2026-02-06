"""Merge feed handler."""

from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from rss_glue.feeds.registry import FeedRegistry, PostDict
from rss_glue.models.db import Feed, FeedTag, Post, Tag


def get_merge_source_ids(feed_id: str, session: Session) -> set[str]:
    """Get all source feed IDs for a merge feed based on its include_tags.

    This is the canonical function for resolving merge feed sources.
    Used by merge handler, digest handler, update service, etc.
    """
    feed = session.get(Feed, feed_id)
    if not feed or feed.type != "merge":
        return set()

    include_tags = feed.config.get("include_tags", [])
    if not include_tags:
        return set()

    stmt = (
        select(FeedTag.feed_id).join(Tag).where(Tag.name.in_(include_tags))  # type: ignore[attr-defined]
    )
    return set(session.exec(stmt).all())


@FeedRegistry.register("merge")
class MergeFeedHandler:
    """Handler for merge feeds - combines posts from sources matching tags."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Merge feeds don't fetch external data during update.

        Posts are aggregated from source feeds at query time (RSS generation).
        """
        return []

    @staticmethod
    def next_update(feed: "Feed", session: Session) -> datetime | None:
        """Merge feeds never need automatic updates.

        Their content is derived from source feeds at query time.
        """
        return None

    @staticmethod
    def reset(feed_id: str, session: Session) -> dict[str, int]:
        """Merge feeds don't own any data - nothing to reset."""
        return {}

    @staticmethod
    def get_posts(
        feed_id: str, limit: int, session: Session, base_url: str = ""
    ) -> list[PostDict]:
        """Get posts from all source feeds, sorted by published_at."""
        source_ids = get_merge_source_ids(feed_id, session)

        if not source_ids:
            return []

        # Query posts from all source feeds
        stmt = (
            select(Post)
            .where(Post.feed_id.in_(source_ids))  # type: ignore[union-attr]
            .order_by(Post.published_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        )

        posts = list(session.exec(stmt).all())

        return [
            PostDict(
                id=post.external_id,
                title=post.title,
                link=post.link,
                published_at=post.published_at,
                content=post.content,
                author=post.author,
            )
            for post in posts
        ]
