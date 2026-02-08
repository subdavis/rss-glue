from typing import TYPE_CHECKING

from croniter import croniter
from jinja2.filters import K
from pydantic import BaseModel, Field, field_validator

from rss_glue.models.db import Feed

if TYPE_CHECKING:
    from sqlmodel import Session


class FeedConfigBase(BaseModel):
    """Base configuration for all feed types."""

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1)
    limit: int = Field(default=50, ge=1, le=1000)
    type: str = Field(..., min_length=1)
    cache_media: bool | None = Field(
        default=None,
        description="Cache embedded media. None = use global setting.",
    )
    cooldown_minutes: int | None = Field(
        default=None,
        ge=0,
        le=10080,
        description="Cooldown interval in minutes. None = use global setting.",
    )
    schedule: str | None = Field(
        default=None,
        description="Cron expression for scheduled updates (e.g., '0 0 * * *' for daily). "
        "If set, used instead of cooldown for determining next update time, "
        "but cooldown still applies as minimum interval between updates.",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this feed is enabled and should be updated by the worker.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="List of tags for categorizing and grouping feeds.",
    )

    @field_validator("schedule")
    @classmethod
    def validate_schedule_cron(cls, v: str | None) -> str | None:
        """Validate that schedule is a valid cron expression if provided."""
        if v is not None and not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @classmethod
    def _sample(cls, **kwargs) -> dict:
        """Return a sample representation of the feed config."""
        return cls(
            id="sample-feed",
            name="Sample Feed",
            limit=10,
            cache_media=None,
            cooldown_minutes=None,
            enabled=True,
            tags=["tag1", "tag2"],
            **kwargs,
        ).model_dump()

    @classmethod
    def db_hydrate(
        cls, feed: Feed, session: "Session | None" = None, **kwargs
    ) -> "FeedConfigBase":
        config_obj = cls(
            id=feed.id,
            name=feed.name,
            limit=feed.limit,
            type=feed.type,
            enabled=feed.enabled,
            **kwargs,
        )

        # Restore tags from DB
        if feed.tags:
            config_obj.tags = [tag.name for tag in feed.tags]

        # Restore explicit cache_media setting
        if feed.config.get("cache_media_explicit") is not None:
            config_obj.cache_media = feed.config["cache_media_explicit"]

        # Restore explicit cooldown_minutes setting
        if feed.config.get("cooldown_minutes_explicit") is not None:
            config_obj.cooldown_minutes = feed.config["cooldown_minutes_explicit"]

        # Restore schedule
        if feed.config.get("schedule") is not None:
            config_obj.schedule = feed.config.get("schedule", None)

        return config_obj

    def extra_config(self) -> dict:
        """Return any additional config fields that should be stored in the DB."""
        config_dict = {}

        # Store explicit cache_media setting if present
        if self.cache_media is not None:
            config_dict["cache_media_explicit"] = self.cache_media

        # Store explicit cooldown_minutes setting if present
        if self.cooldown_minutes is not None:
            config_dict["cooldown_minutes_explicit"] = self.cooldown_minutes

        if self.schedule is not None:
            config_dict["schedule"] = self.schedule

        return config_dict
