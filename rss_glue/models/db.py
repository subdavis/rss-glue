"""SQLModel database models."""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, TypeDecorator
from sqlmodel import JSON, Column, Field, Relationship, SQLModel


class UTCDateTime(TypeDecorator):
    """SQLAlchemy type that ensures datetimes are timezone-aware (UTC).

    SQLite doesn't preserve timezone info, so naive datetimes from the DB
    are assumed to be UTC and converted to timezone-aware.
    """

    impl = DateTime
    cache_ok = True

    def process_result_value(
        self, value: Optional[datetime], dialect: Any
    ) -> Optional[datetime]:
        """Add UTC timezone to naive datetimes loaded from the database."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class FeedRelationship(SQLModel, table=True):
    """Many-to-many relationship for merge feeds referencing source feeds."""

    __tablename__ = "feed_relationship"

    parent_feed_id: str = Field(foreign_key="feed.id", primary_key=True)
    child_feed_id: str = Field(foreign_key="feed.id", primary_key=True)
    position: int = Field(default=0)


class Feed(SQLModel, table=True):
    """Feed configuration stored in database."""

    __tablename__ = "feed"

    id: str = Field(primary_key=True)
    type: str
    name: str
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    limit: int = Field(default=50)
    cache_media: bool = Field(default=False)
    cooldown_minutes: Optional[int] = Field(default=None)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime, nullable=False),
    )
    updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(UTCDateTime, nullable=True)
    )

    posts: list["Post"] = Relationship(
        back_populates="feed",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    update_history: list["UpdateHistory"] = Relationship(
        back_populates="feed",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    cached_media: list["MediaCache"] = Relationship(
        back_populates="feed",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Post(SQLModel, table=True):
    """Individual feed posts."""

    __tablename__ = "post"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: str = Field(foreign_key="feed.id", index=True)
    external_id: str
    title: str
    content: Optional[str] = None
    link: str
    author: Optional[str] = None
    score: Optional[int] = None
    published_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime, nullable=False),
    )

    feed: Feed = Relationship(back_populates="posts")
    cached_media: list["MediaCache"] = Relationship(
        back_populates="post",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    enclosures: list["Enclosure"] = Relationship(
        back_populates="post",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class UpdateHistory(SQLModel, table=True):
    """Track feed update attempts."""

    __tablename__ = "update_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: str = Field(foreign_key="feed.id", index=True)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime, nullable=False),
    )
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(UTCDateTime, nullable=True)
    )
    status: str = Field(default="running")
    error_message: Optional[str] = None
    posts_added: int = Field(default=0)

    feed: Feed = Relationship(back_populates="update_history")


class MediaCache(SQLModel, table=True):
    """Cached media files from feed posts."""

    __tablename__ = "media_cache"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: str = Field(foreign_key="feed.id", index=True)
    post_id: int = Field(foreign_key="post.id", index=True)
    original_url: str = Field(index=True)
    local_path: str
    content_type: Optional[str] = None
    cached_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(UTCDateTime, nullable=False),
    )

    feed: Feed = Relationship(back_populates="cached_media")
    post: Post = Relationship(back_populates="cached_media")


class SystemConfig(SQLModel, table=True):
    """Global system configuration."""

    __tablename__ = "system_config"

    key: str = Field(primary_key=True)
    value: str


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


class Enclosure(SQLModel, table=True):
    """RSS enclosures (attachments) for posts."""

    __tablename__ = "enclosure"

    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="post.id", index=True)
    url: str  # URL for rendering (may be __BASE_URL__ placeholder if cached)
    original_url: str  # Always the original URL
    local_path: Optional[str] = None  # Cached path (if cached)
    mime_type: Optional[str] = None
    length: Optional[int] = None  # Size in bytes

    post: Post = Relationship(back_populates="enclosures")
