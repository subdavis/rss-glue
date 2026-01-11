"""Cooldown management for feed updates."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from rss_glue.models.db import Feed


def should_update_feed(
    feed: Feed, force: bool = False
) -> tuple[bool, Optional[datetime], str]:
    """Check if a feed should be updated based on cooldown interval.

    Args:
        feed: Feed to check
        force: If True, bypass cooldown check

    Returns:
        Tuple of (should_update, next_update_time, reason)
    """
    if force:
        return True, None, "forced update"

    # Get cooldown from feed's cooldown_minutes field (already resolved by config sync)
    cooldown_minutes = feed.cooldown_minutes or 0

    # If cooldown is 0, always update
    if cooldown_minutes <= 0:
        return True, None, "no cooldown configured"

    # Check when the feed was last updated
    # If updated_at is None, treat as never updated
    if not feed.updated_at:
        return True, None, "never updated"

    # Ensure timezone-aware datetime
    updated_at = feed.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    # Calculate when next update should happen
    cooldown_delta = timedelta(minutes=cooldown_minutes)
    next_update_time = updated_at + cooldown_delta
    current_time = datetime.now(timezone.utc)

    if current_time >= next_update_time:
        return True, next_update_time, "cooldown period elapsed"

    # Still in cooldown period
    minutes_remaining = int((next_update_time - current_time).total_seconds() / 60)
    return (
        False,
        next_update_time,
        f"cooldown active (next update in {minutes_remaining} minutes)",
    )
