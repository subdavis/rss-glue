"""Merge feed handler."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlmodel import Session, select

from rss_glue.feeds.registry import FeedRegistry, PostDict, BaseFeedHandler
from rss_glue.models.db import Feed, FeedTag, Tag
from rss_glue.models.feed_config import FeedConfigBase


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
class MergeFeedHandler(BaseFeedHandler):
    """Handler for merge feeds - combines posts from sources matching tags."""

    class Config(FeedConfigBase):
        """Configuration for a merge feed."""

        type: Literal["merge"]
        include_tags: list[str] = Field(default_factory=list, min_length=1)

        def extra_config(self) -> dict:
            """Return any additional config fields needed for DB storage."""
            return {
                **super().extra_config(),
                "include_tags": self.include_tags,
            }

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
        feed_id: str,
        limit: int,
        session: Session,
        base_url: str = "",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> list[PostDict]:
        """Get posts from all source feeds, sorted by published_at.

        Calls each source feed handler's get_posts() instead of querying the
        Post table directly. This enables arbitrary nesting (merges of merges,
        merges of smart_filters, etc.) and preserves source metadata opaquely.
        """
        source_ids = get_merge_source_ids(feed_id, session)

        if not source_ids:
            return []

        all_posts: list[PostDict] = []
        for source_id in source_ids:
            source_feed = session.get(Feed, source_id)
            if not source_feed:
                continue
            handler = FeedRegistry.get_handler(source_feed.type)
            # Fetch all posts from source (no limit), apply our limit after merging
            posts = handler.get_posts(
                source_id, 0, session, base_url, period_start, period_end
            )
            all_posts.extend(posts)

        # Sort merged posts by published_at descending
        all_posts.sort(key=lambda p: p["published_at"], reverse=True)

        if limit > 0:
            all_posts = all_posts[:limit]

        return all_posts
