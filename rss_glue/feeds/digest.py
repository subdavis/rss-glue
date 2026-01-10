"""Digest feed handler - creates periodic rollups based on cron schedule."""
from datetime import datetime
from typing import Any

from croniter import croniter
from sqlmodel import Session, select, and_

from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import (
    DigestIssue,
    DigestIssuePost,
    Feed,
    FeedRelationship,
    Post,
)


def get_source_feed_id(feed_id: str, session: Session) -> str | None:
    """Get the source feed ID for a digest feed from FeedRelationship."""
    stmt = select(FeedRelationship.child_feed_id).where(
        FeedRelationship.parent_feed_id == feed_id
    )
    return session.exec(stmt).first()


def get_posts_for_period(
    source_id: str,
    period_start: datetime,
    period_end: datetime,
    limit: int,
    session: Session,
) -> list[Post]:
    """Get posts from source feed within a time period."""
    source_feed = session.get(Feed, source_id)
    if not source_feed:
        return []

    # Check if source is a merge feed - if so, get from all its sources
    if source_feed.type == "merge":
        source_ids = _get_all_source_ids(source_id, session)
    else:
        source_ids = [source_id]

    stmt = (
        select(Post)
        .where(
            and_(
                Post.feed_id.in_(source_ids),
                Post.published_at >= period_start,
                Post.published_at < period_end,
            )
        )
        .order_by(Post.published_at.desc())
        .limit(limit)
    )

    return list(session.exec(stmt).all())


def _get_all_source_ids(merge_feed_id: str, session: Session) -> list[str]:
    """Recursively get all source feed IDs for a merge feed."""
    stmt = (
        select(FeedRelationship.child_feed_id)
        .where(FeedRelationship.parent_feed_id == merge_feed_id)
        .order_by(FeedRelationship.position)
    )
    child_ids = list(session.exec(stmt).all())

    result = []
    for child_id in child_ids:
        child_feed = session.get(Feed, child_id)
        if child_feed and child_feed.type == "merge":
            result.extend(_get_all_source_ids(child_id, session))
        else:
            result.append(child_id)

    return result


def calculate_missing_periods(
    schedule: str, last_issue_end: datetime | None, now: datetime
) -> list[tuple[datetime, datetime]]:
    """Calculate digest periods that need to be created.

    Returns list of (period_start, period_end) tuples.
    """
    if last_issue_end is None:
        # No previous issues - start from one period ago
        cron = croniter(schedule, now)
        cron.get_prev(datetime)  # Go back one period
        start_time = cron.get_prev(datetime)  # And one more to get start
        cron = croniter(schedule, start_time)
    else:
        # Start from the last issue end time
        cron = croniter(schedule, last_issue_end)

    periods = []
    while True:
        period_start = cron.get_current(datetime)
        period_end = cron.get_next(datetime)

        # Only include complete periods (period_end <= now)
        if period_end > now:
            break

        periods.append((period_start, period_end))

    return periods


def get_latest_digest_issue(feed_id: str, session: Session) -> DigestIssue | None:
    """Get the most recent digest issue for a feed."""
    stmt = (
        select(DigestIssue)
        .where(DigestIssue.feed_id == feed_id)
        .order_by(DigestIssue.period_end.desc())
        .limit(1)
    )
    return session.exec(stmt).first()


def create_digest_issue(
    feed_id: str,
    source_id: str,
    period_start: datetime,
    period_end: datetime,
    limit: int,
    session: Session,
) -> DigestIssue:
    """Create a new digest issue for the given period."""
    # Get posts for this period
    posts = get_posts_for_period(source_id, period_start, period_end, limit, session)

    # Create the digest issue
    issue = DigestIssue(
        feed_id=feed_id,
        period_start=period_start,
        period_end=period_end,
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)

    # Link posts to the issue
    for position, post in enumerate(posts):
        link = DigestIssuePost(
            digest_issue_id=issue.id,
            post_id=post.id,
            position=position,
        )
        session.add(link)

    session.commit()
    session.refresh(issue)
    return issue


@FeedRegistry.register("digest")
class DigestFeedHandler:
    """Handler for digest feeds - creates periodic rollups of source feed posts."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Create digest issues for any missing periods.

        Unlike RSS feeds, digest doesn't return posts directly.
        Instead it creates DigestIssue records that are converted to
        RSS items during output generation.
        """
        schedule = config.get("schedule")
        limit = config.get("limit", 20)

        if not schedule:
            return []

        # Get source feed ID from relationship
        source_id = get_source_feed_id(feed_id, session)
        if not source_id:
            return []

        # Find the latest existing digest issue
        latest_issue = get_latest_digest_issue(feed_id, session)
        last_issue_end = latest_issue.period_end if latest_issue else None

        # Calculate missing periods
        now = datetime.utcnow()
        missing_periods = calculate_missing_periods(schedule, last_issue_end, now)

        # Create digest issues for each missing period
        issues_created = 0
        for period_start, period_end in missing_periods:
            create_digest_issue(
                feed_id, source_id, period_start, period_end, limit, session
            )
            issues_created += 1

        # Return empty list - digest items are served via get_digest_issues()
        return []

    @staticmethod
    def get_digest_issues(
        feed_id: str, limit: int, session: Session
    ) -> list[DigestIssue]:
        """Get digest issues for RSS output, most recent first."""
        stmt = (
            select(DigestIssue)
            .where(DigestIssue.feed_id == feed_id)
            .order_by(DigestIssue.period_end.desc())
            .limit(limit)
        )
        return list(session.exec(stmt).all())

    @staticmethod
    def get_issue_posts(issue_id: int, session: Session) -> list[Post]:
        """Get posts for a specific digest issue in order."""
        stmt = (
            select(Post)
            .join(DigestIssuePost, DigestIssuePost.post_id == Post.id)
            .where(DigestIssuePost.digest_issue_id == issue_id)
            .order_by(DigestIssuePost.position)
        )
        return list(session.exec(stmt).all())
