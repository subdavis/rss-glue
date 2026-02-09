"""RSS feed handler."""

from pydantic import Field
from rss_glue.models.feed_config import FeedConfigBase

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

import feedparser
from sqlmodel import Session

from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry


@FeedRegistry.register("rss")
class RssFeedHandler(BaseFeedHandler):
    """Handler for RSS/Atom feeds."""

    class Config(FeedConfigBase):
        """Configuration for an RSS source feed."""

        type: Literal["rss"]
        url: str = Field(..., pattern=r"^https?://")

        def extra_config(self) -> dict:
            """Return any additional config fields needed for DB storage."""
            return {
                **super().extra_config(),
                "url": self.url,
            }

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch and parse RSS feed."""
        url = config["url"]
        limit = config.get("limit", 50)

        parsed = feedparser.parse(url)
        posts = []

        for entry in parsed.entries[:limit]:
            # Generate stable external ID from entry id or link
            raw_id = getattr(entry, "id", None) or entry.link
            external_id = hashlib.sha256(raw_id.encode()).hexdigest()[:16]

            # Parse published date
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6])
            else:
                published = datetime.now(timezone.utc)

            # Extract content
            content = None
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary

            # Extract enclosures
            enclosures = []
            if hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    enclosures.append(
                        {
                            "url": enc.get("href", ""),
                            "mime_type": enc.get("type"),
                            "length": int(enc.get("length", 0))
                            if enc.get("length")
                            else None,
                        }
                    )

            posts.append(
                {
                    "external_id": external_id,
                    "title": getattr(entry, "title", "Untitled"),
                    "content": content,
                    "link": entry.link,
                    "author": getattr(entry, "author", None),
                    "published_at": published,
                    "enclosures": enclosures,
                }
            )

        return posts
