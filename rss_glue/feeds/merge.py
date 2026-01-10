"""Merge feed handler."""
from typing import Any

from sqlmodel import Session, select

from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import Post, FeedRelationship


@FeedRegistry.register("merge")
class MergeFeedHandler:
    """Handler for merge feeds - combines posts from multiple sources."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Merge feeds don't fetch external data during update.

        Posts are aggregated from source feeds at query time (RSS generation).
        """
        return []

    @staticmethod
    def get_merged_posts(feed_id: str, limit: int, session: Session) -> list[Post]:
        """Get posts from all source feeds, sorted by published_at."""
        # Get source feed IDs in order
        stmt = (
            select(FeedRelationship.child_feed_id)
            .where(FeedRelationship.parent_feed_id == feed_id)
            .order_by(FeedRelationship.position)
        )
        source_ids = list(session.exec(stmt).all())

        if not source_ids:
            return []

        # Query posts from all source feeds
        stmt = (
            select(Post)
            .where(Post.feed_id.in_(source_ids))
            .order_by(Post.published_at.desc())
            .limit(limit)
        )

        return list(session.exec(stmt).all())
