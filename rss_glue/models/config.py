"""Pydantic models for JSON configuration validation."""
from typing import Literal, Annotated, Union

from croniter import croniter
from pydantic import BaseModel, Field, field_validator, model_validator


class RssFeedConfig(BaseModel):
    """Configuration for an RSS source feed.

    Example:
        {
            "id": "hackernews",
            "type": "rss",
            "name": "Hacker News",
            "url": "https://news.ycombinator.com/rss",
            "limit": 50,
            "cache_media": true
        }
    """

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["rss"]
    name: str = Field(..., min_length=1)
    url: str = Field(..., pattern=r"^https?://")
    limit: int = Field(default=50, ge=1, le=1000)
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )


class MergeFeedConfig(BaseModel):
    """Configuration for a merge feed that combines multiple sources.

    Example:
        {
            "id": "tech-news",
            "type": "merge",
            "name": "Tech News",
            "sources": ["hackernews", "lobsters"],
            "limit": 100
        }
    """

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["merge"]
    name: str = Field(..., min_length=1)
    sources: list[str] = Field(..., min_length=1)
    limit: int = Field(default=100, ge=1, le=1000)
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )


class DigestFeedConfig(BaseModel):
    """Configuration for a digest feed that creates periodic rollups.

    Example:
        {
            "id": "weekly-digest",
            "type": "digest",
            "name": "Weekly Digest",
            "source": "tech-news",
            "schedule": "0 0 * * 0",
            "limit": 20
        }
    """

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["digest"]
    name: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1, description="Single source feed ID")
    schedule: str = Field(
        ...,
        min_length=1,
        description="Cron expression like '0 0 * * 0' (weekly Sunday midnight)",
    )
    limit: int = Field(default=20, ge=1, le=1000, description="Posts per digest")
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )

    @field_validator("schedule")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Validate that schedule is a valid cron expression."""
        if not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v


class HackerNewsFeedConfig(BaseModel):
    """Configuration for a HackerNews feed.

    Example:
        {
            "id": "hn",
            "type": "hackernews",
            "name": "HN",
            "story_type": "top",
            "limit": 30
        }
    """

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["hackernews"]
    name: str = Field(..., min_length=1)
    story_type: Literal["top", "new", "best"] = Field(default="top")
    limit: int = Field(default=30, ge=1, le=500)
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )


class InstagramFeedConfig(BaseModel):
    """Configuration for an Instagram feed.

    Uses ScrapeCreators API.
    Requires `scrape_creators_key` to be set in AppConfig.

    Example:
        {
            "id": "ig",
            "type": "instagram",
            "name": "My Instagram",
            "username": "natgeo",
            "limit": 20
        }
    """

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["instagram"]
    name: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1, description="Instagram username (without @)")
    limit: int = Field(default=20, ge=1, le=100)
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )


class FacebookFeedConfig(BaseModel):
    """Configuration for a Facebook page/group feed.

    Uses ScrapeCreators API.
    Requires `scrape_creators_key` to be set in AppConfig.

    Example:
        {
            "id": "fb",
            "type": "facebook",
            "name": "My FB Page",
            "url": "https://www.facebook.com/groups/12345",
            "limit": 20
        }
    """

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["facebook"]
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1, description="Facebook Page or Group URL")
    limit: int = Field(default=20, ge=1, le=100)
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )


class RedditFeedConfig(BaseModel):
    """Configuration for a Reddit feed.

    Example:
        {
            "id": "reddit-selfhosted",
            "type": "reddit",
            "name": "r/selfhosted",
            "subreddit": "selfhosted",
            "listing_type": "top",
            "time_filter": "week",
            "limit": 20
        }
    """

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["reddit"]
    name: str = Field(..., min_length=1)
    subreddit: str = Field(..., min_length=1)
    listing_type: Literal["hot", "new", "top", "rising"] = Field(default="top")
    time_filter: Literal["hour", "day", "week", "month", "year", "all"] | None = Field(
        default="day", description="Only used for 'top' listing"
    )
    limit: int = Field(default=20, ge=1, le=100)
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )


FeedConfig = Annotated[
    Union[
        RssFeedConfig,
        MergeFeedConfig,
        DigestFeedConfig,
        HackerNewsFeedConfig,
        InstagramFeedConfig,
        FacebookFeedConfig,
        RedditFeedConfig,
    ],
    Field(discriminator="type"),
]


class AppConfig(BaseModel):
    """Root configuration schema.

    Example:
        {
            "cache_media": true,
            "scrape_creators_key": "sc_...",
            "feeds": [
                {"id": "hn", "type": "rss", "name": "HN", "url": "https://..."},
                {"id": "all", "type": "merge", "name": "All", "sources": ["hn"]}
            ]
        }
    """

    cache_media: bool = Field(
        default=False,
        description="Global setting to cache embedded media from feed posts.",
    )
    scrape_creators_key: str | None = Field(
        default=None,
        description="API Key for ScrapeCreators service (required for Instagram/Facebook).",
    )
    feeds: list[FeedConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_no_duplicate_ids(self) -> "AppConfig":
        """Ensure all feed IDs are unique."""
        ids = [feed.id for feed in self.feeds]
        if len(ids) != len(set(ids)):
            seen = set()
            duplicates = []
            for id in ids:
                if id in seen:
                    duplicates.append(id)
                seen.add(id)
            raise ValueError(f"Duplicate feed IDs: {duplicates}")
        return self

    @model_validator(mode="after")
    def validate_references(self) -> "AppConfig":
        """Validate that merge and digest feeds only reference existing feed IDs."""
        feed_ids = {feed.id for feed in self.feeds}

        for feed in self.feeds:
            if feed.type == "merge":
                for source_id in feed.sources:
                    if source_id not in feed_ids:
                        raise ValueError(
                            f"Merge feed '{feed.id}' references unknown feed '{source_id}'"
                        )
            elif feed.type == "digest":
                if feed.source not in feed_ids:
                    raise ValueError(
                        f"Digest feed '{feed.id}' references unknown feed '{feed.source}'"
                    )
        return self

    @model_validator(mode="after")
    def validate_no_cycles(self) -> "AppConfig":
        """Detect circular dependencies in merge and digest feeds."""
        deps: dict[str, set[str]] = {}
        for feed in self.feeds:
            if feed.type == "merge":
                deps[feed.id] = set(feed.sources)
            elif feed.type == "digest":
                deps[feed.id] = {feed.source}
            else:
                deps[feed.id] = set()

        def has_cycle(node: str, visited: set[str], path: set[str]) -> bool:
            visited.add(node)
            path.add(node)
            for neighbor in deps.get(node, set()):
                if neighbor in path:
                    return True
                if neighbor not in visited and has_cycle(neighbor, visited, path):
                    return True
            path.remove(node)
            return False

        visited: set[str] = set()
        for feed_id in deps:
            if feed_id not in visited:
                if has_cycle(feed_id, visited, set()):
                    raise ValueError(
                        f"Circular dependency detected involving '{feed_id}'"
                    )

        return self
