"""Feed type registry for extensibility."""

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
    content: str | None
    author: str | None
    enclosures: list[EnclosureDict]


class FeedHandler(Protocol):
    """Protocol for feed type handlers."""

    @staticmethod
    def fetch(
        feed_id: str, config: dict[str, Any], session: Session
    ) -> list[dict] | None | int:
        """Fetch posts from the feed source.

        Returns list of post dicts with keys:
        - external_id: str
        - title: str
        - content: str | None
        - link: str
        - author: str | None
        - published_at: datetime

        If return is None, indicates no work was done, no history should be recorded (e.g., no new posts).
        If return is int, indicates number of items created for reporting purposes (for digest feeds).
        """
        ...

    @staticmethod
    def get_posts(
        feed_id: str, limit: int, session: Session, base_url: str = ""
    ) -> list[PostDict]:
        """Get posts for rendering HTML or RSS output.

        Returns list of PostDict with standardized keys:
        - id: str (unique identifier)
        - title: str
        - link: str
        - published_at: datetime
        - content: str | None
        - author: str | None
        """
        ...

    @staticmethod
    def next_update(feed: "Feed", session: Session) -> datetime | None:
        """Calculate when this feed should next be updated.

        Returns:
            datetime: Next scheduled update time (may be in past if overdue)
            None: Feed is manual-only (no automatic updates)
        """
        ...

    @staticmethod
    def reset(feed_id: str, session: Session) -> dict[str, int]:
        """Reset feed-specific data (posts, digest issues, etc).

        Does NOT reset update history or updated_at - that's handled by the caller.

        Returns:
            Dict with counts of deleted items (posts_deleted, etc.)
        """
        ...


class BaseFeedHandler:
    """Base class for feed handlers with default implementations."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
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
        cooldown_minutes = feed.cooldown_minutes or 0
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

    _handlers: dict[str, Type[FeedHandler]] = {}

    @classmethod
    def register(
        cls, feed_type: str
    ) -> Callable[[Type[FeedHandler]], Type[FeedHandler]]:
        """Decorator to register a feed handler.

        Usage:
            @FeedRegistry.register("rss")
            class RssFeedHandler:
                @staticmethod
                def fetch(feed_id, config, session):
                    ...
        """

        def decorator(handler_cls: Type[FeedHandler]) -> Type[FeedHandler]:
            cls._handlers[feed_type] = handler_cls
            return handler_cls

        return decorator

    @classmethod
    def get_handler(cls, feed_type: str) -> Type[FeedHandler]:
        """Get handler for a feed type."""
        if feed_type not in cls._handlers:
            raise ValueError(f"Unknown feed type: {feed_type}")
        return cls._handlers[feed_type]

    @classmethod
    def supported_types(cls) -> list[str]:
        """List all registered feed types."""
        return list(cls._handlers.keys())
