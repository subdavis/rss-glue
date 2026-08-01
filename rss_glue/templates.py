"""Centralized Jinja2 template configuration with custom filters."""

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from rss_glue.services.timezone import format_datetime, get_display_timezone

# Templates directory
templates_dir = Path(__file__).parent / "templates"

# Create templates instance
templates = Jinja2Templates(directory=str(templates_dir))


def localtime_filter(dt: datetime | None, format_name: str = "default") -> str:
    """Jinja2 filter to convert UTC datetime to local display timezone.

    Usage in templates:
        {{ some_datetime | localtime }}              # Uses "default" format: 2026-01-13 14:30
        {{ some_datetime | localtime("relative") }}  # Shows relative time: "2 hours ago"
        {{ some_datetime | localtime("tooltip") }}   # For title attributes: 2026-01-13 14:30:45 EST

    Available format presets:
        - "default": %Y-%m-%d %H:%M (e.g., "2026-01-13 14:30")
        - "relative": Relative time (e.g., "2 minutes ago", "yesterday", "3 days ago")
        - "tooltip": %Y-%m-%d %H:%M:%S %Z (e.g., "2026-01-13 14:30:45 EST") - for title attributes

    Args:
        dt: A datetime object in UTC (or None)
        format_name: Name of the format preset (default: "default")

    Returns:
        Formatted datetime string in the display timezone
    """
    if dt is None:
        return ""
    return format_datetime(dt, format_name)


def weburl_filter(url: str | None) -> str:
    """Resolve a stored __BASE_URL__ link to a same-origin relative URL.

    HTML pages are served from the same origin, so the placeholder just drops out.
    RSS and the JSON API need absolute URLs and use `expand_placeholders` instead.
    """
    return (url or "").replace("__BASE_URL__", "")


# Register custom filters
templates.env.filters["localtime"] = localtime_filter
templates.env.filters["weburl"] = weburl_filter

# Add display_timezone as a global variable for templates
templates.env.globals["display_timezone"] = get_display_timezone
