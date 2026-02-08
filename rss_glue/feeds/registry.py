"""Feed type registry for extensibility."""

from rss_glue.models.feed_config import FeedConfigBase

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Protocol, Type, TypedDict

from croniter import croniter
from sqlmodel import Session, select

from rss_glue.models.db import MediaCache, Post
from rss_glue.services.timezone import get_display_timezone

if TYPE_CHECKING:
    from rss_glue.models.db import Feed


class EnclosureDict(TypedDict, total=False):
    """Standardized enclosure dictionary for templates and RSS output."""

    url: str
    original_url: str
    mime_type: str | None
    length: int | None


class PostDict(TypedDict, total=False):
    """Standardized post dictionary for templates and RSS output."""

    id: str
    title: str
    link: str
    published_at: datetime
    content: str
    author: str | None
    enclosures: list[EnclosureDict]


class BaseFeedHandler:
    """Base class for feed handlers with default implementations."""

    class Config(FeedConfigBase):
        pass

    @staticmethod
    def fetch(
        feed_id: str, config: dict[str, Any], session: Session
    ) -> list[dict] | None | int:
        """Fetch posts from the feed source. Must be overridden."""
        raise NotImplementedError("Subclass must implement fetch()")

    @staticmethod
    def get_posts(
        feed_id: str, limit: int, session: Session, base_url: str = ""
    ) -> list[PostDict]:
        """Default implementation: query posts from the database.

        This works for standard feeds (rss, hackernews, instagram, etc.)
        that store posts directly in the Post table.
        """
        stmt = (
            select(Post)
            .where(Post.feed_id == feed_id)
            .order_by(Post.published_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        posts = list(session.exec(stmt).all())

        result = []
        for post in posts:
            # Get enclosures for this post
            enclosures = [
                EnclosureDict(
                    url=enc.url,
                    original_url=enc.original_url,
                    mime_type=enc.mime_type,
                    length=enc.length,
                )
                for enc in post.enclosures
            ]
            result.append(
                PostDict(
                    id=post.external_id,
                    title=post.title,
                    link=post.link,
                    published_at=post.published_at,
                    content=post.content,
                    author=post.author,
                    enclosures=enclosures,
                )
            )
        return result

    @staticmethod
    def next_update(feed: "Feed", session: Session) -> datetime | None:
        """Default implementation: cooldown and/or schedule-based scheduling.

        If schedule is set, uses cron schedule for timing (with cooldown as minimum interval).
        If no schedule, uses cooldown-based scheduling.
        Returns None for manual-only feeds (no schedule and cooldown_minutes <= 0).
        """
        from rss_glue.services.config_sync import resolve_feed_cooldown

        cooldown_minutes = resolve_feed_cooldown(feed, session)
        schedule = feed.config.get("schedule")

        # Never updated - schedule immediately
        if feed.updated_at is None:
            return datetime.now(timezone.utc)

        # Calculate cooldown-based next time
        if cooldown_minutes > 0:
            cooldown_time: datetime | None = feed.updated_at + timedelta(
                minutes=cooldown_minutes
            )
        else:
            cooldown_time = None

        # Calculate schedule-based next time
        # Cron schedule is interpreted in the display timezone
        schedule_time: datetime | None = None
        if schedule:
            try:
                display_tz = get_display_timezone()
                updated_local = feed.updated_at.astimezone(display_tz)
                cron = croniter(schedule, updated_local)
                schedule_time = cron.get_next(datetime).astimezone(timezone.utc)
            except (ValueError, KeyError):
                schedule_time = None

        # Determine next update time
        if schedule_time is not None and cooldown_time is not None:
            # Both set - must satisfy both conditions
            return max(schedule_time, cooldown_time)
        elif schedule_time is not None:
            # Only schedule - use it
            return schedule_time
        elif cooldown_time is not None:
            # Only cooldown - use it
            return cooldown_time
        else:
            # Neither - manual only
            return None

    @staticmethod
    def reset(feed_id: str, session: Session) -> dict[str, int]:
        """Default implementation: delete posts and media cache entries.

        Works for standard feeds that store posts directly in the Post table.
        """
        # Get media entries for counting
        media_entries = list(
            session.exec(select(MediaCache).where(MediaCache.feed_id == feed_id)).all()
        )

        # Delete posts (cascades to MediaCache via relationship)
        posts = list(session.exec(select(Post).where(Post.feed_id == feed_id)).all())
        for post in posts:
            session.delete(post)

        return {
            "posts_deleted": len(posts),
            "media_deleted": len(media_entries),
        }


class FeedRegistry:
    """Registry for feed type handlers."""

    _handlers: dict[str, Type[BaseFeedHandler]] = {}

    @classmethod
    def register(
        cls, feed_type: str
    ) -> Callable[[Type[BaseFeedHandler]], Type[BaseFeedHandler]]:
        """Decorator to register a feed handler.

        Usage:
            @FeedRegistry.register("type")
            class TypeFeedHandler:
                @staticmethod
                def fetch(feed_id, config, session):
                    ...
        """

        def decorator(handler_cls: Type[BaseFeedHandler]) -> Type[BaseFeedHandler]:
            cls._handlers[feed_type] = handler_cls
            return handler_cls

        return decorator

    @classmethod
    def get_handler(cls, feed_type: str) -> Type[BaseFeedHandler]:
        """Get handler for a feed type."""
        if feed_type not in cls._handlers:
            raise ValueError(f"Unknown feed type: {feed_type}")
        return cls._handlers[feed_type]

    @classmethod
    def supported_types(cls) -> list[str]:
        """List all registered feed types."""
        return list(cls._handlers.keys())
