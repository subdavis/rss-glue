"""RSS feed handler."""
import hashlib
from datetime import datetime
from typing import Any

import feedparser
from sqlmodel import Session

from rss_glue.feeds.registry import FeedRegistry


@FeedRegistry.register("rss")
class RssFeedHandler:
    """Handler for RSS/Atom feeds."""

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
                published = datetime.utcnow()

            # Extract content
            content = None
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary

            posts.append(
                {
                    "external_id": external_id,
                    "title": getattr(entry, "title", "Untitled"),
                    "content": content,
                    "link": entry.link,
                    "author": getattr(entry, "author", None),
                    "published_at": published,
                }
            )

        return posts
