"""Smart filter feed handler - filters source posts using Anthropic API."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Column, Field, Session, SQLModel, select

from rss_glue.feeds.registry import (
    BaseFeedHandler,
    EnclosureDict,
    FeedRegistry,
    PostDict,
)
from rss_glue.models.db import (
    Feed,
    FeedRelationship,
    Post,
    SystemConfig,
    UTCDateTime,
)

logger = logging.getLogger(__name__)


class FilterDecision(SQLModel, table=True):
    """Record of a smart filter decision for a source post."""

    __tablename__ = "filter_decision"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: str = Field(foreign_key="feed.id", index=True)
    post_id: int = Field(foreign_key="post.id", index=True)
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


def _get_all_source_ids(source_id: str, session: Session) -> list[str]:
    """Get all underlying source IDs, resolving merge feeds."""
    source_feed = session.get(Feed, source_id)
    if not source_feed:
        return []

    if source_feed.type == "merge":
        from rss_glue.feeds.merge import get_merge_source_ids

        child_ids = get_merge_source_ids(source_id, session)
        result = []
        for child_id in child_ids:
            child_feed = session.get(Feed, child_id)
            if child_feed and child_feed.type == "merge":
                result.extend(_get_all_source_ids(child_id, session))
            else:
                result.append(child_id)
        return result
    else:
        return [source_id]


def get_unevaluated_posts(
    feed_id: str, source_ids: list[str], session: Session
) -> list[Post]:
    """Get source posts that haven't been evaluated by this filter yet."""
    # Get IDs of already-evaluated posts
    evaluated_stmt = select(FilterDecision.post_id).where(
        FilterDecision.feed_id == feed_id
    )
    evaluated_ids = set(session.exec(evaluated_stmt).all())

    # Get all source posts
    stmt = (
        select(Post)
        .where(Post.feed_id.in_(source_ids))  # type: ignore[union-attr]
        .order_by(Post.published_at.desc())  # type: ignore[union-attr]
    )
    all_posts = list(session.exec(stmt).all())

    return [p for p in all_posts if p.id not in evaluated_ids]


def evaluate_post(
    post: Post, prompt: str, api_key: str, model: str
) -> tuple[bool, str]:
    """Call Anthropic API to evaluate a post against the filter prompt.

    Returns (approved, reason).
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Build post context
    post_text = f"Title: {post.title}\n"
    if post.author:
        post_text += f"Author: {post.author}\n"
    if post.link:
        post_text += f"Link: {post.link}\n"
    post_text += f"Published: {post.published_at.isoformat()}\n"
    if post.content:
        post_text += f"\nContent:\n{post.content}\n"

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


@FeedRegistry.register("smart_filter")
class SmartFilterFeedHandler:
    """Handler for smart filter feeds - filters source posts using LLM."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> None | int:
        """Evaluate unevaluated source posts against the filter prompt."""
        prompt = config.get("prompt")
        model = config.get("model", "claude-haiku-4-0")

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

        # Resolve source to actual feed IDs (handles merge feeds)
        source_ids = _get_all_source_ids(source_id, session)
        if not source_ids:
            return None

        # Get posts that haven't been evaluated yet
        unevaluated = get_unevaluated_posts(feed_id, source_ids, session)
        if not unevaluated:
            return None

        decisions_made = 0
        for post in unevaluated:
            try:
                approved, reason = evaluate_post(post, prompt, api_key, model)
                decision = FilterDecision(
                    feed_id=feed_id,
                    post_id=post.id,
                    approved=approved,
                    reason=reason,
                )
                session.add(decision)
                decisions_made += 1
            except Exception:
                logger.exception(
                    "Failed to evaluate post %s for filter %s", post.id, feed_id
                )
                # Continue with remaining posts rather than failing entirely
                continue

        if decisions_made > 0:
            session.commit()
            return decisions_made

        return None

    @staticmethod
    def next_update(feed: Feed, session: Session) -> datetime | None:
        """Use default cooldown/schedule-based scheduling."""
        return BaseFeedHandler.next_update(feed, session)

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
        feed_id: str, limit: int, session: Session, base_url: str = ""
    ) -> list[PostDict]:
        """Get approved posts from the source feed."""
        # Get approved post IDs
        approved_stmt = select(FilterDecision.post_id).where(
            FilterDecision.feed_id == feed_id,
            FilterDecision.approved == True,  # noqa: E712
        )
        approved_ids = list(session.exec(approved_stmt).all())

        if not approved_ids:
            return []

        # Get the actual posts
        stmt = (
            select(Post)
            .where(Post.id.in_(approved_ids))  # type: ignore[union-attr]
            .order_by(Post.published_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        )
        posts = list(session.exec(stmt).all())

        result = []
        for post in posts:
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
