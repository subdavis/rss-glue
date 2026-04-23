"""Pydantic models for JSON configuration validation."""

from rss_glue.feeds.squarespace_cal import SquarespaceCalFeedHandler
from rss_glue.feeds.merge import MergeFeedHandler
from rss_glue.feeds.wordpress_mec_events import WordPressMecEventsFeedHandler
from rss_glue.feeds.reddit import RedditFeedHandler
from rss_glue.feeds.facebook import FacebookFeedHandler
from rss_glue.feeds.instagram import InstagramFeedHandler
from rss_glue.feeds.hackernews import HackerNewsFeedHandler
from rss_glue.feeds.rss import RssFeedHandler
from typing import Annotated, Union

from rss_glue.feeds.smart_filter import SmartFilterFeedHandler
from rss_glue.feeds.digest import DigestFeedHandler

from pydantic import BaseModel, Field, model_validator

FeedConfig = Annotated[
    Union[
        SmartFilterFeedHandler.Config,
        DigestFeedHandler.Config,
        RssFeedHandler.Config,
        HackerNewsFeedHandler.Config,
        InstagramFeedHandler.Config,
        FacebookFeedHandler.Config,
        RedditFeedHandler.Config,
        WordPressMecEventsFeedHandler.Config,
        SquarespaceCalFeedHandler.Config,
        MergeFeedHandler.Config,
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
    anthropic_api_key: str | None = Field(
        default=None,
        description="API Key for Anthropic (required for smart_filter feeds).",
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
        """Validate that digest and smart_filter feeds reference existing feed IDs."""
        feed_ids = {feed.id for feed in self.feeds}

        for feed in self.feeds:
            if isinstance(
                feed, (DigestFeedHandler.Config, SmartFilterFeedHandler.Config)
            ):
                if feed.source not in feed_ids:
                    raise ValueError(
                        f"{feed.type} feed '{feed.id}' references unknown feed '{feed.source}'"
                    )
        return self

    @model_validator(mode="after")
    def validate_no_cycles(self) -> "AppConfig":
        """Detect circular dependencies in digest and smart_filter feeds.

        Note: Merge feeds use tag-based sources which are resolved at runtime,
        so cycle detection for them happens at the database level.
        """
        deps: dict[str, set[str]] = {}
        for feed in self.feeds:
            if isinstance(
                feed, (DigestFeedHandler.Config, SmartFilterFeedHandler.Config)
            ):
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
