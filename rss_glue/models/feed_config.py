from typing import TYPE_CHECKING

from croniter import croniter
from pydantic import BaseModel, Field, field_validator

from rss_glue.models.db import Feed

if TYPE_CHECKING:
    from sqlmodel import Session


class FeedConfigBase(BaseModel):
    """Base configuration for all feed types.

    ## Extending for a new handler

    Subclass this in your handler file and set `type` to a Literal matching the
    handler's registered key.  Override `extra_config()` to return any fields that
    need to be persisted in the Feed.config JSON column.  Override `db_hydrate()` if
    the config requires a session lookup (e.g. FeedRelationship for digest/smart_filter).

    ## Form rendering

    Every handler Config subclass gets a paired Jinja2 partial at
    `templates/configs/<type>.html`.  That partial should `{% include 'configs/base.html' %}`
    (which renders the shared fields below) and then add its own handler-specific fields.
    The shell template `templates/feed_config.html` dynamically includes the right partial
    based on the feed type.

    ## Global-overridable fields

    `cooldown_minutes` and `cache_media` are tri-state: None means "use the global default."
    The form renders the effective global value as a placeholder/label so users can see
    what they're inheriting.  `upsert_feed()` in config_sync.py coerces empty form
    strings back to None before validation.
    """

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
        return cls(
            id=feed.id,
            name=feed.name,
            limit=feed.limit,
            type=feed.type,
            enabled=feed.enabled,
            cache_media=feed.cache_media,
            cooldown_minutes=feed.cooldown_minutes,
            tags=[tag.name for tag in feed.tags] if feed.tags else [],
            **kwargs,
        )

    def extra_config(self) -> dict:
        """Return any additional config fields that should be stored in the DB."""
        config_dict = {}

        if self.schedule is not None:
            config_dict["schedule"] = self.schedule

        return config_dict
