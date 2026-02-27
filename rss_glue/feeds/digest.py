"""Digest feed handler - creates periodic rollups based on cron schedule."""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from croniter import croniter
from sqlmodel import Field, Session, select, SQLModel, Column, Relationship

from rss_glue.feeds.registry import FeedRegistry, PostDict, BaseFeedHandler
from rss_glue.models.db import (
    Feed,
    FeedRelationship,
    Post,
    UTCDateTime,
)
from rss_glue.models.feed_config import FeedConfigBase
from rss_glue.services.timezone import get_display_timezone
from rss_glue.templates import templates


class DigestIssue(SQLModel, table=True):
    """A digest issue representing a rollup of posts for a time period."""

    __tablename__ = "digest_issue"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: str = Field(foreign_key="feed.id", index=True)
    period_start: datetime = Field(
        sa_column=Column(UTCDateTime, index=True, nullable=False)
    )
    period_end: datetime = Field(
        sa_column=Column(UTCDateTime, index=True, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime, nullable=False),
    )

    posts: list["DigestIssuePost"] = Relationship(
        back_populates="digest_issue",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class DigestIssuePost(SQLModel, table=True):
    """Link between digest issue and posts included in it."""

    __tablename__ = "digest_issue_post"

    id: Optional[int] = Field(default=None, primary_key=True)
    digest_issue_id: int = Field(foreign_key="digest_issue.id", index=True)
    post_id: int = Field(foreign_key="post.id", index=True)
    position: int = Field(default=0)

    digest_issue: DigestIssue = Relationship(back_populates="posts")
    post: Post = Relationship()


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
) -> list[PostDict]:
    """Get posts from source feed within a time period.

    Uses source handler's get_posts() for composability instead of
    querying the Post table directly. This enables digests of merges,
    smart_filters, or any other feed type.
    """
    source_feed = session.get(Feed, source_id)
    if not source_feed:
        return []

    handler = FeedRegistry.get_handler(source_feed.type)
    posts = handler.get_posts(
        source_id, 0, session, "", period_start, period_end
    )

    # Sort by score descending (digest shows best posts first)
    posts.sort(
        key=lambda p: (p.get("metadata", {}).get("score") or 0),
        reverse=True,
    )

    if limit > 0:
        posts = posts[:limit]

    return posts


def calculate_missing_periods(
    schedule: str, last_issue_end: datetime | None, now: datetime
) -> list[tuple[datetime, datetime]]:
    """Calculate digest periods that need to be created.

    Cron schedule is interpreted in the display timezone.
    All input/output datetimes are UTC.

    Returns list of (period_start, period_end) tuples in UTC.
    """
    display_tz = get_display_timezone()
    now_local = now.astimezone(display_tz)

    if last_issue_end is None:
        # No previous issues - start from one period ago
        cron = croniter(schedule, now_local)
        cron.get_prev(datetime)  # Go back one period
        start_time = cron.get_prev(datetime)  # And one more to get start
        cron = croniter(schedule, start_time)
    else:
        # Start from the last issue end time
        last_end_local = last_issue_end.astimezone(display_tz)
        cron = croniter(schedule, last_end_local)

    periods = []
    while True:
        period_start = cron.get_current(datetime).astimezone(timezone.utc)
        period_end = cron.get_next(datetime).astimezone(timezone.utc)

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
        .order_by(DigestIssue.period_end.desc())  # type: ignore[union-attr]
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
    """Create a new digest issue for the given period.

    Uses source handler's get_posts() for composability. Links to Post
    records via post_id from PostDict when available.
    """
    # Get posts for this period via source handler
    post_dicts = get_posts_for_period(
        source_id, period_start, period_end, limit, session
    )

    # Create the digest issue
    issue = DigestIssue(
        feed_id=feed_id,
        period_start=period_start,
        period_end=period_end,
    )
    session.add(issue)
    session.commit()
    session.refresh(issue)

    # Link posts to the issue (only when post_id is available)
    for position, post_dict in enumerate(post_dicts):
        post_id = post_dict.get("post_id")
        if post_id is not None:
            link = DigestIssuePost(
                digest_issue_id=issue.id,
                post_id=post_id,
                position=position,
            )
            session.add(link)

    session.commit()
    session.refresh(issue)
    return issue


def format_digest_issue_content(posts: list[PostDict]) -> str:
    """Generate HTML content for a digest issue with full article content."""
    template = templates.env.get_template("feeds/digest.html")
    return template.render(posts=posts)


@FeedRegistry.register("digest")
class DigestFeedHandler(BaseFeedHandler):
    """Handler for digest feeds - creates periodic rollups of source feed posts."""

    class Config(FeedConfigBase):
        """Configuration for a digest feed.

        Note: source_id is stored via FeedRelationship, not in config.
        """

        type: Literal["digest"]
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

            return super().db_hydrate(feed, session=session, source=source, **kwargs)

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> None | int:
        """Create digest issues for any missing periods.

        Unlike RSS feeds, digest doesn't return posts directly.
        Instead it creates DigestIssue records that are converted to
        RSS items during output generation.
        """
        schedule = config.get("schedule")
        limit = config.get("limit", 20)

        if not schedule:
            return None

        # Get source feed ID from relationship
        source_id = get_source_feed_id(feed_id, session)
        if not source_id:
            return None

        # Find the latest existing digest issue
        latest_issue = get_latest_digest_issue(feed_id, session)
        last_issue_end = latest_issue.period_end if latest_issue else None

        # Calculate missing periods
        now = datetime.now(timezone.utc)
        missing_periods = calculate_missing_periods(schedule, last_issue_end, now)

        # Create digest issues for each missing period
        issues_created = 0
        for period_start, period_end in missing_periods:
            create_digest_issue(
                feed_id, source_id, period_start, period_end, limit, session
            )
            issues_created += 1

        # Return empty list - digest items are served via get_posts()
        if issues_created > 0:
            return issues_created

        return None

    @staticmethod
    def next_update(feed: Feed, session: Session) -> datetime | None:
        """Calculate when the next digest issue should be created.

        Returns the end time of the next period that will be due.
        This may be in the past if issues are overdue.
        Returns None if no schedule is configured.
        """
        schedule = feed.config.get("schedule")
        if not schedule:
            return None  # Manual-only

        try:
            # Cron schedule is interpreted in the display timezone
            display_tz = get_display_timezone()

            # Get the latest digest issue to find where we left off
            latest_issue = get_latest_digest_issue(feed.id, session)

            if latest_issue is None:
                # No previous issues - calculate from one period ago
                now_local = datetime.now(display_tz)
                cron = croniter(schedule, now_local)
                # Go back one period to find the closing time of the first issue
                next_time = cron.get_prev(datetime)
            else:
                # Start from the last issue end time plus one second (to avoid confusion with exact matches)
                last_end_local = (
                    latest_issue.period_end + timedelta(seconds=1)
                ).astimezone(display_tz)
                cron = croniter(schedule, last_end_local)
                # The next issue end time is the next scheduled time
                next_time = cron.get_next(datetime)

            return next_time.astimezone(timezone.utc)
        except (ValueError, KeyError):
            return None  # Invalid cron schedule

    @staticmethod
    def reset(feed_id: str, session: Session) -> dict[str, int]:
        """Delete digest issues (cascades to DigestIssuePost)."""
        digest_issues = list(
            session.exec(
                select(DigestIssue).where(DigestIssue.feed_id == feed_id)
            ).all()
        )
        for issue in digest_issues:
            session.delete(issue)

        return {"digest_issues_deleted": len(digest_issues)}

    @staticmethod
    def get_posts(
        feed_id: str,
        limit: int,
        session: Session,
        base_url: str = "",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> list[PostDict]:
        """Get digest issues formatted as posts for RSS/HTML output."""
        # Get feed name for titles
        feed = session.get(Feed, feed_id)
        feed_name = feed.name if feed else feed_id

        # Get digest issues
        stmt = select(DigestIssue).where(DigestIssue.feed_id == feed_id)
        if period_start is not None:
            stmt = stmt.where(DigestIssue.period_end >= period_start)
        if period_end is not None:
            stmt = stmt.where(DigestIssue.period_end < period_end)
        stmt = stmt.order_by(DigestIssue.period_end.desc())  # type: ignore[union-attr]
        if limit > 0:
            stmt = stmt.limit(limit)
        issues = list(session.exec(stmt).all())

        result: list[PostDict] = []
        for issue in issues:
            if issue.id is None:
                continue

            # Get posts for this issue
            issue_posts = DigestFeedHandler._get_issue_posts(issue.id, session)
            content = format_digest_issue_content(issue_posts)

            # Format the title with date range
            start_str = issue.period_start.strftime("%b %d")
            end_str = issue.period_end.strftime("%b %d, %Y")

            result.append(
                PostDict(
                    id=f"digest:{feed_id}:{issue.id}",
                    title=f"{feed_name}: {start_str} - {end_str}",
                    link=f"{base_url}feed/{feed_id}/rss",
                    published_at=issue.period_end,
                    content=content,
                    author="System",
                )
            )

        return result

    @staticmethod
    def _get_issue_posts(issue_id: int, session: Session) -> list[PostDict]:
        """Get posts for a specific digest issue in order.

        Returns PostDicts for template rendering.
        """
        stmt = (
            select(Post)
            .join(DigestIssuePost, DigestIssuePost.post_id == Post.id)  # type: ignore[arg-type]
            .where(DigestIssuePost.digest_issue_id == issue_id)
            .order_by(DigestIssuePost.position)  # type: ignore[arg-type]
        )
        posts = list(session.exec(stmt).all())
        return [
            PostDict(
                id=post.external_id,
                post_id=post.id,
                title=post.title,
                link=post.link,
                published_at=post.published_at,
                content=post.content,
                author=post.author,
            )
            for post in posts
        ]
