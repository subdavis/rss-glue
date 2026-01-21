from croniter import croniter
from pydantic import BaseModel, Field, field_validator


class FeedConfigBase(BaseModel):
    """Base configuration for all feed types."""

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1)
    limit: int = Field(default=50, ge=1, le=1000)
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

    @field_validator("schedule")
    @classmethod
    def validate_schedule_cron(cls, v: str | None) -> str | None:
        """Validate that schedule is a valid cron expression if provided."""
        if v is not None and not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v
