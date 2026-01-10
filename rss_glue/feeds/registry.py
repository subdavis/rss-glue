"""Feed type registry for extensibility."""
from typing import Protocol, Type, Callable, Any

from sqlmodel import Session


class FeedHandler(Protocol):
    """Protocol for feed type handlers."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch posts from the feed source.

        Returns list of post dicts with keys:
        - external_id: str
        - title: str
        - content: str | None
        - link: str
        - author: str | None
        - published_at: datetime
        """
        ...


class FeedRegistry:
    """Registry for feed type handlers."""

    _handlers: dict[str, Type[FeedHandler]] = {}

    @classmethod
    def register(cls, feed_type: str) -> Callable[[Type[FeedHandler]], Type[FeedHandler]]:
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
