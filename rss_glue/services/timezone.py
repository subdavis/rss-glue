"""Timezone utilities for converting UTC times to display timezone."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Named format presets (for non-relative formats)
FORMAT_PRESETS = {
    "default": "%Y-%m-%d %H:%M",
    "tooltip": "%Y-%m-%d %H:%M:%S %Z",
}


def get_display_timezone() -> ZoneInfo:
    """Get the display timezone from environment variable.

    Returns:
        ZoneInfo: The configured display timezone, defaulting to America/New_York
    """
    tz_name = os.getenv("DISPLAY_TIMEZONE", "America/New_York")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        # Fallback to America/New_York if invalid timezone
        return ZoneInfo("America/New_York")


def to_display_timezone(dt: datetime | None) -> datetime | None:
    """Convert a UTC datetime to the display timezone.

    Args:
        dt: A datetime object in UTC (or None)

    Returns:
        The datetime converted to the display timezone, or None if input was None
    """
    if dt is None:
        return None

    # Ensure the datetime is timezone-aware (should already be UTC from DB)
    if dt.tzinfo is None:
        # If naive, assume UTC
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    # Convert to display timezone
    display_tz = get_display_timezone()
    return dt.astimezone(display_tz)


def format_relative_time(dt: datetime | None) -> str:
    """Format a datetime as relative time (e.g., '2 minutes ago', 'in 3 hours').

    Args:
        dt: A datetime object in UTC (or None)

    Returns:
        Relative time string, or empty string if dt is None
    """
    if dt is None:
        return ""

    # Convert to display timezone
    converted = to_display_timezone(dt)
    if converted is None:
        return ""

    # Get current time in display timezone
    now = datetime.now(get_display_timezone())

    # Calculate difference
    diff = now - converted
    total_seconds = diff.total_seconds()
    is_future = total_seconds < 0

    if is_future:
        # Handle future times
        total_seconds = abs(total_seconds)
        suffix = "from now"
    else:
        suffix = "ago"

    # Convert to appropriate units
    if total_seconds < 60:
        return "just now" if not is_future else "in a moment"
    elif total_seconds < 3600:  # Less than 1 hour
        minutes = int(total_seconds / 60)
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} {suffix}"
    elif total_seconds < 86400:  # Less than 1 day
        hours = int(total_seconds / 3600)
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} {suffix}"
    elif total_seconds < 172800:  # Less than 2 days
        if is_future:
            return "tomorrow"
        else:
            return "yesterday"
    elif total_seconds < 604800:  # Less than 7 days
        days = int(total_seconds / 86400)
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} {suffix}"
    elif total_seconds < 2592000:  # Less than 30 days
        weeks = int(total_seconds / 604800)
        unit = "week" if weeks == 1 else "weeks"
        return f"{weeks} {unit} {suffix}"
    elif total_seconds < 31536000:  # Less than 1 year
        months = int(total_seconds / 2592000)
        unit = "month" if months == 1 else "months"
        return f"{months} {unit} {suffix}"
    else:
        years = int(total_seconds / 31536000)
        unit = "year" if years == 1 else "years"
        return f"{years} {unit} {suffix}"


def format_datetime(dt: datetime | None, format_name: str = "default") -> str:
    """Format a datetime in the display timezone using a named format preset.

    Args:
        dt: A datetime object in UTC (or None)
        format_name: Name of the format preset ("default", "relative", or a strftime format string)

    Returns:
        Formatted datetime string, or empty string if dt is None
    """
    if dt is None:
        return ""

    # Handle special "relative" format
    if format_name == "relative":
        return format_relative_time(dt)

    converted = to_display_timezone(dt)
    if converted is None:
        return ""

    # Get format string from preset, or use as literal format if not found
    fmt = FORMAT_PRESETS.get(format_name, format_name)
    return converted.strftime(fmt)
