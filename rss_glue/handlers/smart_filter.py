"""Smart filter feed handler - filters source posts using Anthropic API."""

import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import Field as PydanticField
from sqlmodel import Column, Field, Session, SQLModel, select

from rss_glue.feeds.registry import (
    BaseFeedHandler,
    FeedRegistry,
    PostDict,
)
from rss_glue.models.db import (
    Feed,
    FeedRelationship,
    SystemConfig,
    UTCDateTime,
)
from rss_glue.models.feed_config import FeedConfigBase

logger = logging.getLogger(__name__)


class FilterDecision(SQLModel, table=True):
    """Record of a smart filter decision for a source post."""

    __tablename__ = "filter_decision"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: str = Field(foreign_key="feed.id", index=True)
    post_external_id: str = Field(index=True)
    approved: bool = Field(default=False)
    reason: Optional[str] = None
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime, nullable=False),
    )


def get_source_feed_id(feed_id: str, session: Session) -> str | None:
    """Get the source feed ID for a smart filter feed from FeedRelationship."""
    stmt = select(FeedRelationship.child_feed_id).where(
        FeedRelationship.parent_feed_id == feed_id
    )
    return session.exec(stmt).first()


def get_unevaluated_posts(
    feed_id: str, source_posts: list[PostDict], session: Session
) -> list[PostDict]:
    """Filter source posts to those not yet evaluated by this filter."""
    evaluated_stmt = select(FilterDecision.post_external_id).where(
        FilterDecision.feed_id == feed_id
    )
    evaluated_ids = set(session.exec(evaluated_stmt).all())
    return [p for p in source_posts if p["id"] not in evaluated_ids]


def evaluate_post(
    post: PostDict, prompt: str, api_key: str, model: str
) -> tuple[bool, str]:
    """Call Anthropic API to evaluate a post against the filter prompt.

    Returns (approved, reason).
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Build post context
    post_text = f"Title: {post['title']}\n"
    if post.get("author"):
        post_text += f"Author: {post['author']}\n"
    if post.get("link"):
        post_text += f"Link: {post['link']}\n"
    post_text += f"Published: {post['published_at'].isoformat()}\n"
    if post.get("content"):
        post_text += f"\nContent:\n{post['content']}\n"

    system_prompt = (
        "You are a feed post filter. You will be given a blog/feed post and a filtering question. "
        "You must decide whether this post matches the filter criteria.\n\n"
        "Respond with EXACTLY one line: either 'YES' or 'NO', followed by a brief reason.\n"
        "Example: 'YES: This post announces a local meetup event.'\n"
        "Example: 'NO: This post is a technical tutorial, not an event.'"
    )

    user_message = f"Filter question: {prompt}\n\n---\n\n{post_text}"

    message = client.messages.create(
        model=model,
        max_tokens=150,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    response_text = message.content[0].text.strip()

    # Parse response
    approved = response_text.upper().startswith("YES")
    reason = response_text

    return approved, reason


def _get_source_handler(source_id: str, session: Session):
    """Get the feed handler for a source feed."""
    source_feed = session.get(Feed, source_id)
    if not source_feed:
        return None, None
    return source_feed, FeedRegistry.get_handler(source_feed.type)


@FeedRegistry.register("smart_filter")
class SmartFilterFeedHandler(BaseFeedHandler):
    """Handler for smart filter feeds - filters source posts using LLM."""

    class Config(FeedConfigBase):
        """Configuration for a smart filter feed.

        Note: source_id is stored via FeedRelationship, not in config.
        """

        type: Literal["smart_filter"]
        prompt: str = PydanticField(..., min_length=1)
        model: str = PydanticField(default="claude-haiku-4-5")
        source: str = Field(..., min_length=1, description="Single source feed ID")

        @classmethod
        def db_hydrate(cls, feed: Feed, session: Session | None = None, **kwargs):
            """Return any additional fields needed for DB storage."""
            # Get source feed ID from FeedRelationship
            source = ""
            if session:
                rel = session.exec(
                    select(FeedRelationship).where(
                        FeedRelationship.parent_feed_id == feed.id
                    )
                ).first()
                source = rel.child_feed_id if rel else ""

            return super().db_hydrate(
                feed,
                session=session,
                source=source,
                **kwargs,
            )

        def extra_config(self) -> dict:
            """Return any additional config fields needed for DB storage."""
            # Note: source is NOT stored in config, it's stored in FeedRelationship table
            return {
                **super().extra_config(),
                "prompt": self.prompt,
                "model": self.model,
            }

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> None | int:
        """Evaluate unevaluated source posts against the filter prompt.

        Uses source handler's get_posts() for composability instead of
        querying the Post table directly.
        """
        prompt = config.get("prompt")
        model = config.get("model", "claude-haiku-4-5")

        if not prompt:
            logger.error("Smart filter feed %s has no prompt configured", feed_id)
            return None

        # Get API key from system config
        api_key_config = session.get(SystemConfig, "anthropic_api_key")
        if not api_key_config:
            logger.error("No anthropic_api_key configured in system settings")
            return None
        api_key = api_key_config.value

        # Get source feed ID
        source_id = get_source_feed_id(feed_id, session)
        if not source_id:
            logger.error("Smart filter feed %s has no source configured", feed_id)
            return None

        # Get all posts from source handler (composable - handles merges, etc.)
        source_feed, handler = _get_source_handler(source_id, session)
        if not handler:
            return None

        source_posts = handler.get_posts(source_id, 0, session, "")

        # Find posts that haven't been evaluated yet
        unevaluated = get_unevaluated_posts(feed_id, source_posts, session)
        if not unevaluated:
            return None

        decisions_made = 0
        for post_dict in unevaluated:
            try:
                approved, reason = evaluate_post(post_dict, prompt, api_key, model)
                decision = FilterDecision(
                    feed_id=feed_id,
                    post_external_id=post_dict["id"],
                    approved=approved,
                    reason=reason,
                )
                session.add(decision)
                decisions_made += 1
            except Exception:
                logger.exception(
                    "Failed to evaluate post %s for filter %s",
                    post_dict["id"],
                    feed_id,
                )
                # Continue with remaining posts rather than failing entirely
                continue

        if decisions_made > 0:
            session.commit()
            return decisions_made

        return None

    @staticmethod
    def next_update(feed: Feed, session: Session) -> datetime | None:
        """Return now if there are unevaluated posts, otherwise None.

        Smart filter is purely reactive - it only needs to run when the
        source has new posts that haven't been evaluated yet.
        """
        source_id = get_source_feed_id(feed.id, session)
        if not source_id:
            return None

        source_feed, handler = _get_source_handler(source_id, session)
        if not handler:
            return None

        source_posts = handler.get_posts(source_id, 0, session, "")
        unevaluated = get_unevaluated_posts(feed.id, source_posts, session)
        if unevaluated:
            return datetime.now(timezone.utc)

        return None

    @staticmethod
    def reset(feed_id: str, session: Session) -> dict[str, int]:
        """Delete filter decisions for this feed."""
        decisions = list(
            session.exec(
                select(FilterDecision).where(FilterDecision.feed_id == feed_id)
            ).all()
        )
        for decision in decisions:
            session.delete(decision)

        return {"decisions_deleted": len(decisions)}

    @staticmethod
    def get_posts(
        feed_id: str,
        limit: int,
        session: Session,
        base_url: str = "",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> list[PostDict]:
        """Get approved posts from the source feed.

        Calls source handler's get_posts() and filters by approved decisions.
        This enables composability - source can be any feed type.
        Metadata from source posts is preserved opaquely.
        """
        source_id = get_source_feed_id(feed_id, session)
        if not source_id:
            return []

        source_feed, handler = _get_source_handler(source_id, session)
        if not handler:
            return []

        # Get all source posts (no limit), we'll filter and apply our limit
        source_posts = handler.get_posts(
            source_id, 0, session, base_url, period_start, period_end
        )

        # Get approved external IDs for this filter
        approved_stmt = select(FilterDecision.post_external_id).where(
            FilterDecision.feed_id == feed_id,
            FilterDecision.approved == True,  # noqa: E712
        )
        approved_ids = set(session.exec(approved_stmt).all())

        if not approved_ids:
            return []

        # Filter source posts by approved decisions, preserving metadata
        result = [p for p in source_posts if p["id"] in approved_ids]

        if limit > 0:
            result = result[:limit]

        return result
