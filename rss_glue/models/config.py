"""Pydantic models for JSON configuration validation."""

from typing import Annotated, Literal, Union

from croniter import croniter
from pydantic import BaseModel, Field, field_validator, model_validator

from rss_glue.models.feed_config import FeedConfigBase


class RssFeedConfig(FeedConfigBase):
    """Configuration for an RSS source feed."""

    type: Literal["rss"]
    url: str = Field(..., pattern=r"^https?://")


class MergeFeedConfig(FeedConfigBase):
    """Configuration for a merge feed that combines multiple sources by tags.

    Example:
        {
            "id": "tech-news",
            "type": "merge",
            "name": "Tech News",
            "include_tags": ["tech", "coding"],
            "limit": 100
        }
    """

    type: Literal["merge"]
    include_tags: list[str] = Field(
        ..., min_length=1, description="Include feeds that have any of these tags."
    )


class DigestFeedConfig(FeedConfigBase):
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

    type: Literal["digest"]
    source: str = Field(..., min_length=1, description="Single source feed ID")
    schedule: str = Field(
        ...,
        min_length=1,
        description="Cron expression like '0 0 * * 0' (weekly Sunday midnight)",
    )

    @field_validator("schedule")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Validate that schedule is a valid cron expression."""
        if not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v


class HackerNewsFeedConfig(FeedConfigBase):
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

    type: Literal["hackernews"]
    story_type: Literal["top", "new", "best"] = Field(default="top")


class InstagramFeedConfig(FeedConfigBase):
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

    type: Literal["instagram"]
    username: str = Field(
        ..., min_length=1, description="Instagram username (without @)"
    )


class FacebookFeedConfig(FeedConfigBase):
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

    type: Literal["facebook"]
    url: str = Field(..., min_length=1, description="Facebook Page or Group URL")


class RedditFeedConfig(FeedConfigBase):
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

    type: Literal["reddit"]
    subreddit: str = Field(..., min_length=1)
    listing_type: Literal["hot", "new", "top", "rising"] = Field(default="top")
    time_filter: Literal["hour", "day", "week", "month", "year", "all"] | None = Field(
        default="day", description="Only used for 'top' listing"
    )


class WordPressMecEventsFeedConfig(FeedConfigBase):
    """Configuration for WordPress pages using Modern Events Calendar plugin.

    Extracts events from rendered HTML, filtering out recurring events
    that appear on the page more than the threshold number of times.

    Example:
        {
            "id": "bikemn",
            "type": "wordpress_mec_events",
            "name": "BikeMN Events",
            "url": "https://www.bikemn.org/wp-json/wp/v2/pages/2454",
            "recurring_threshold": 3
        }
    """

    type: Literal["wordpress_mec_events"]
    url: str = Field(..., pattern=r"^https?://")
    recurring_threshold: int = Field(
        default=3,
        ge=2,
        description="Titles appearing this many times or more are treated as recurring and excluded.",
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
        WordPressMecEventsFeedConfig,
    ],
    Field(discriminator="type"),
]


class AppConfig(BaseModel):
    """Root configuration schema.

    Example:
        {
            "cache_media": true,
            "scrape_creators_key": "sc_...",
            "default_cooldown_minutes": 15,
            "feeds": [
                {"id": "hn", "type": "rss", "name": "HN", "url": "https://...", "tags": ["tech"]},
                {"id": "all", "type": "merge", "name": "All", "include_tags": ["tech"]}
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
    default_cooldown_minutes: int = Field(
        default=15,
        ge=0,
        le=10080,  # Max 7 days
        description="Global default cooldown interval in minutes between feed updates.",
    )
    base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for generating absolute links in RSS feeds.",
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
        """Validate that digest feeds only reference existing feed IDs."""
        feed_ids = {feed.id for feed in self.feeds}

        for feed in self.feeds:
            if isinstance(feed, DigestFeedConfig):
                if feed.source not in feed_ids:
                    raise ValueError(
                        f"Digest feed '{feed.id}' references unknown feed '{feed.source}'"
                    )
        return self

    @model_validator(mode="after")
    def validate_no_cycles(self) -> "AppConfig":
        """Detect circular dependencies in digest feeds.

        Note: Merge feeds use tag-based sources which are resolved at runtime,
        so cycle detection for them happens at the database level.
        """
        deps: dict[str, set[str]] = {}
        for feed in self.feeds:
            if isinstance(feed, DigestFeedConfig):
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
