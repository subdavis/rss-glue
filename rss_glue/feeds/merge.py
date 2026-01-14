"""Merge feed handler."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

from rss_glue.feeds.registry import FeedRegistry, PostDict
from rss_glue.models.db import FeedRelationship, Post

if TYPE_CHECKING:
    from rss_glue.models.db import Feed


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
        # Get source feed IDs in order
        stmt = (
            select(FeedRelationship.child_feed_id)
            .where(FeedRelationship.parent_feed_id == feed_id)
            .order_by(FeedRelationship.position)  # type: ignore[arg-type]
        )
        source_ids = list(session.exec(stmt).all())

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
