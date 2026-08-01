"""Email feed handler — one feed per recipient address in a shared IMAP inbox.

Module is named `imap_email` so it doesn't shadow the stdlib `email` package.
"""

import logging
from typing import Any, Literal

from pydantic import Field
from sqlmodel import Session

from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.models.feed_config import FeedConfigBase
from rss_glue.services.imap_inbox import (
    fetch_message,
    get_imap_settings,
    message_to_post,
    scan_window,
)

logger = logging.getLogger(__name__)


@FeedRegistry.register("email")
class EmailFeedHandler(BaseFeedHandler):
    """Turns messages addressed to `address` into posts."""

    class Config(FeedConfigBase):
        type: Literal["email"]
        address: str = Field(..., pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

        def extra_config(self) -> dict:
            return {**super().extra_config(), "address": self.address}

    @staticmethod
    def config_form_context(session: Session) -> dict:
        settings = get_imap_settings(session)
        return {"imap_user": settings.user if settings else None}

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        address = config["address"].strip().lower()
        limit = config.get("limit", 50)

        matches = [e for e in scan_window(session) if address in e.recipients]
        matches.sort(key=lambda e: e.internaldate, reverse=True)

        posts = []
        for entry in matches[:limit]:
            msg = fetch_message(session, entry)
            if msg is None:
                continue
            posts.append(message_to_post(msg, feed_id, entry))

        logger.info("Email feed %s: %d messages for %s", feed_id, len(posts), address)
        return posts
