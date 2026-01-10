"""SQLModel database models."""
from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Relationship, Column, JSON


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

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
    published_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)

    feed: Feed = Relationship(back_populates="posts")
    cached_media: list["MediaCache"] = Relationship(
        back_populates="post",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class UpdateHistory(SQLModel, table=True):
    """Track feed update attempts."""

    __tablename__ = "update_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    feed_id: str = Field(foreign_key="feed.id", index=True)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
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
    cached_at: datetime = Field(default_factory=datetime.utcnow)

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
    period_start: datetime = Field(index=True)
    period_end: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
