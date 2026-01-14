from pydantic import BaseModel, Field

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
    enabled: bool = Field(
        default=True,
        description="Whether this feed is enabled and should be updated by the worker.",
    )
