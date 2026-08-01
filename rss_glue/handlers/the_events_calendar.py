"""WordPress The Events Calendar (tribe/events) REST API feed handler."""

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import Field
from sqlmodel import Session

from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.models.feed_config import FeedConfigBase

_HEADERS = {"User-Agent": "RSS-Glue/2.0 (Feed Aggregator)"}


@FeedRegistry.register("the_events_calendar")
class TheEventsCalendarFeedHandler(BaseFeedHandler):
    """Handler for WordPress sites running The Events Calendar plugin.

    Fetches events from the tribe/events/v1 REST API, supporting pagination
    and filtering to upcoming events only.
    """

    class Config(FeedConfigBase):
        """Configuration for a The Events Calendar source feed."""

        type: Literal["the_events_calendar"]
        base_url: str = Field(
            ...,
            pattern=r"^https?://",
            description="tribe/events/v1 namespace URL, e.g. https://example.com/wp-json/tribe/events/v1",
        )

        def extra_config(self) -> dict:
            return {**super().extra_config(), "base_url": self.base_url}

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch upcoming events from The Events Calendar REST API."""
        base_url = config["base_url"].rstrip("/")
        limit = config.get("limit", 50)

        now = datetime.now(timezone.utc)
        # starts_after accepts "YYYY-MM-DD HH:MM:SS" in site-local time, but UTC
        # works fine for filtering — slightly conservative, never misses events
        starts_after = now.strftime("%Y-%m-%d %H:%M:%S")

        events_url = f"{base_url}/events"
        params: dict[str, Any] = {
            "per_page": min(limit, 50),
            "starts_after": starts_after,
            "status": "publish",
        }

        posts: list[dict] = []
        seen_ids: set[str] = set()
        next_url: str | None = events_url

        while next_url and len(posts) < limit:
            response = httpx.get(
                next_url,
                params=params,
                timeout=30.0,
                headers=_HEADERS,
                follow_redirects=True,
            )
            response.raise_for_status()
            data = response.json()

            events = data.get("events", [])
            if not events:
                break

            for event in events:
                parsed = TheEventsCalendarFeedHandler._parse_event(event)
                if not parsed:
                    continue

                external_id = TheEventsCalendarFeedHandler._generate_id(parsed)
                if external_id in seen_ids:
                    continue
                seen_ids.add(external_id)

                content = TheEventsCalendarFeedHandler._build_content(parsed)

                enclosures = []
                if parsed.get("image_url"):
                    enclosures.append(
                        {
                            "url": parsed["image_url"],
                            "mime_type": "image/jpeg",
                            "length": None,
                        }
                    )

                posts.append(
                    {
                        "external_id": external_id,
                        "title": parsed["title"],
                        "content": content,
                        "link": parsed["url"],
                        "author": None,
                        "published_at": parsed["published_at"],
                        "enclosures": enclosures,
                    }
                )

                if len(posts) >= limit:
                    break

            # tribe API uses next_rest_url for cursor-based pagination
            next_url = data.get("next_rest_url") or None
            params = {}  # next_rest_url already includes all query params

        return posts

    @staticmethod
    def _parse_event(event: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a single event object from the API response."""
        title = event.get("title", "").strip()
        if not title:
            return None

        event_id = event.get("id")
        url = event.get("url", "")

        # Parse start/end dates with timezone
        tz_name = event.get("timezone", "")
        tz = _resolve_tz(tz_name)

        start_dt = _parse_event_date(event.get("start_date", ""), tz)
        end_dt = _parse_event_date(event.get("end_date", ""), tz)
        all_day: bool = event.get("all_day", False)

        # Publication date: prefer UTC field, fall back to local date field
        date_utc = event.get("date_utc", "")
        date_local = event.get("date", "")
        if date_utc:
            published_at = _parse_event_date(date_utc, None)  # already UTC
        elif date_local:
            published_at = _parse_event_date(date_local, tz)
        else:
            published_at = datetime.now(timezone.utc)

        # Description and excerpt (HTML strings)
        description = event.get("description", "").strip()
        excerpt = event.get("excerpt", "").strip()

        # Cost and website
        cost = event.get("cost", "").strip()
        website = event.get("website", "").strip()

        # Venue
        venue_data = event.get("venue") or {}
        venue = _parse_venue(venue_data) if venue_data else ""

        # Organizers
        organizer_data = event.get("organizer") or []
        organizers = _parse_organizers(organizer_data)

        # Categories and tags (list of objects with "name")
        categories = [
            c["name"] for c in (event.get("categories") or []) if c.get("name")
        ]
        tags = [t["name"] for t in (event.get("tags") or []) if t.get("name")]

        # Image: `image` is either False or an object with a `url` key
        image_obj = event.get("image")
        image_url = ""
        if image_obj and isinstance(image_obj, dict):
            image_url = image_obj.get("url", "")

        return {
            "id": event_id,
            "title": title,
            "url": url,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "all_day": all_day,
            "tz_name": tz_name,
            "description": description,
            "excerpt": excerpt,
            "cost": cost,
            "website": website,
            "venue": venue,
            "organizers": organizers,
            "categories": categories,
            "tags": tags,
            "image_url": image_url,
            "published_at": published_at,
        }

    @staticmethod
    def _generate_id(parsed: dict[str, Any]) -> str:
        raw = (
            str(parsed["id"])
            if parsed.get("id")
            else f"{parsed['title']}-{parsed['start_dt']}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _build_content(parsed: dict[str, Any]) -> str:
        parts = []

        # Date / time
        date_str = _format_datetime_range(
            parsed["start_dt"],
            parsed.get("end_dt"),
            parsed["all_day"],
            parsed["tz_name"],
        )
        if date_str:
            parts.append(f"<p><strong>Date:</strong> {date_str}</p>")

        if parsed.get("venue"):
            parts.append(f"<p><strong>Venue:</strong> {parsed['venue']}</p>")

        if parsed.get("cost"):
            parts.append(f"<p><strong>Cost:</strong> {parsed['cost']}</p>")

        if parsed.get("organizers"):
            parts.append(
                f"<p><strong>Organizer:</strong> {', '.join(parsed['organizers'])}</p>"
            )

        if parsed.get("categories"):
            parts.append(
                f"<p><strong>Categories:</strong> {', '.join(parsed['categories'])}</p>"
            )

        if parsed.get("tags"):
            parts.append(f"<p><strong>Tags:</strong> {', '.join(parsed['tags'])}</p>")

        if parsed.get("description"):
            parts.append(parsed["description"])
        elif parsed.get("excerpt"):
            parts.append(parsed["excerpt"])

        if parsed.get("website") and parsed["website"] != parsed["url"]:
            parts.append(f'<p><a href="{parsed["website"]}">Event Website</a></p>')

        return "\n".join(parts)


def _resolve_tz(tz_name: str) -> ZoneInfo | None:
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return None


def _parse_event_date(date_str: str, tz: ZoneInfo | None) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM:SS' into a timezone-aware UTC datetime."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        naive = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now(timezone.utc)
    local = naive.replace(tzinfo=tz) if tz else naive.replace(tzinfo=timezone.utc)
    return local.astimezone(timezone.utc)


def _parse_venue(venue: dict[str, Any]) -> str:
    """Build a human-readable venue string."""
    parts = []
    name = venue.get("venue", "").strip()
    if name:
        parts.append(name)
    address = venue.get("address", "").strip()
    if address:
        parts.append(address)
    city = venue.get("city", "").strip()
    state = venue.get("stateprovince", "").strip()
    zip_code = venue.get("zip", "").strip()
    city_state = ", ".join(filter(None, [city, state]))
    if city_state:
        parts.append(city_state)
    if zip_code:
        parts.append(zip_code)
    return ", ".join(parts)


def _parse_organizers(organizers: list[dict[str, Any]]) -> list[str]:
    """Extract organizer display names."""
    names = []
    for org in organizers:
        name = org.get("organizer", "").strip()
        if name:
            names.append(name)
    return names


def _format_datetime_range(
    start: datetime, end: datetime | None, all_day: bool, tz_name: str
) -> str:
    """Return a human-readable date/time range string."""
    tz = _resolve_tz(tz_name)
    local_start = start.astimezone(tz) if tz else start

    if all_day:
        result = local_start.strftime("%A, %B %-d, %Y")
        if end:
            local_end = end.astimezone(tz) if tz else end
            if local_start.date() != local_end.date():
                result = f"{result} – {local_end.strftime('%A, %B %-d, %Y')}"
        return result

    def _fmt(dt: datetime) -> str:
        hour = dt.hour % 12 or 12
        return f"{dt.strftime('%A, %B %-d, %Y')} at {hour}:{dt.strftime('%M %p')}"

    result = _fmt(local_start)
    if end:
        local_end = end.astimezone(tz) if tz else end
        if local_start.date() == local_end.date():
            hour = local_end.hour % 12 or 12
            result = f"{result} – {hour}:{local_end.strftime('%M %p')}"
        else:
            result = f"{result} – {_fmt(local_end)}"

    if tz:
        result = f"{result} {local_start.tzname()}"

    return result
