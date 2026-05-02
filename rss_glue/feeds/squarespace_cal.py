"""Squarespace Calendar JSON feed handler."""

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from pydantic import Field
from sqlmodel import Session

from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.models.feed_config import FeedConfigBase


@FeedRegistry.register("squarespace_cal")
class SquarespaceCalFeedHandler(BaseFeedHandler):
    """Handler for Squarespace calendar pages that expose JSON.

    Fetches the embedded JSON payload from a Squarespace events page and
    parses ``upcoming`` / ``past`` event arrays.
    """

    class Config(FeedConfigBase):
        """Configuration for a Squarespace Calendar source feed."""

        type: Literal["squarespace_cal"]
        url: str = Field(..., pattern=r"^https?://")
        include_past: bool = Field(default=False)

        def extra_config(self) -> dict:
            return {
                **super().extra_config(),
                "url": self.url,
                "include_past": self.include_past,
            }

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch and parse events from a Squarespace calendar JSON endpoint."""
        url = _json_url(config["url"])
        limit = config.get("limit", 100)
        include_past = config.get("include_past", False)

        headers = {"User-Agent": "RSS-Glue/2.0 (Feed Aggregator)"}
        response = httpx.get(url, timeout=30.0, headers=headers, follow_redirects=True)
        response.raise_for_status()

        data = response.json()
        website = data.get("website", {})
        base_url = website.get("baseUrl", "")
        site_tz = website.get("timeZone")

        now = datetime.now(timezone.utc)
        posts = []
        seen_ids: set[str] = set()

        event_lists = [data.get("upcoming", [])]
        if include_past:
            event_lists.append(data.get("past", []))

        for event_list in event_lists:
            for event in event_list:
                event_data = SquarespaceCalFeedHandler._parse_event(
                    event, base_url, site_tz
                )
                if not event_data:
                    continue

                if not include_past and event_data["start_dt"] < now:
                    continue

                external_id = SquarespaceCalFeedHandler._generate_id(event_data)
                if external_id in seen_ids:
                    continue
                seen_ids.add(external_id)

                content = SquarespaceCalFeedHandler._build_content(event_data)

                enclosures = []
                if event_data.get("image_url"):
                    enclosures.append(
                        {
                            "url": event_data["image_url"],
                            "mime_type": event_data.get("image_mime_type")
                            or "image/jpeg",
                            "length": None,
                        }
                    )

                posts.append(
                    {
                        "external_id": external_id,
                        "title": event_data["title"],
                        "content": content,
                        "link": event_data["link"],
                        "author": None,
                        "published_at": event_data["published_at"],
                        "enclosures": enclosures,
                    }
                )

                if len(posts) >= limit:
                    break

            if len(posts) >= limit:
                break

        return posts

    @staticmethod
    def _parse_event(
        event: dict[str, Any], base_url: str, site_tz: str | None
    ) -> dict[str, Any] | None:
        """Parse a single event from the JSON payload."""
        title = event.get("title", "").strip()
        if not title:
            return None

        # Link: make absolute if relative
        full_url = event.get("fullUrl", "")
        if full_url and not full_url.startswith("http"):
            link = f"{base_url.rstrip('/')}/{full_url.lstrip('/')}"
        else:
            link = full_url

        # Dates: ms timestamps → UTC datetime
        start_ms = event.get("startDate")
        end_ms = event.get("endDate")
        publish_ms = event.get("publishOn") or event.get("addedOn")
        start_dt = _ms_to_utc(start_ms) if start_ms else datetime.now(timezone.utc)
        end_dt = _ms_to_utc(end_ms) if end_ms else None
        published_at = (
            _ms_to_utc(publish_ms) if publish_ms else datetime.now(timezone.utc)
        )

        # Location
        location_parts = []
        loc = event.get("location", {})
        for key in ("addressTitle", "addressLine1", "addressLine2", "addressCountry"):
            val = loc.get(key, "").strip()
            if val:
                location_parts.append(val)
        location = ", ".join(location_parts)

        lat = loc.get("markerLat")
        lng = loc.get("markerLng")
        map_link = ""
        if lat is not None and lng is not None:
            map_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"

        # Tags / categories
        tags = event.get("tags", [])
        categories = event.get("categories", [])

        # Content fields
        excerpt = event.get("excerpt", "").strip()
        raw_body = event.get("body", "").strip()
        body = SquarespaceCalFeedHandler._sanitize_body(raw_body) if raw_body else ""

        # Image
        asset_url = event.get("assetUrl", "")
        content_type = event.get("contentType", "")
        # Some events have a placeholder text/html assetUrl when no real image exists
        if content_type and not content_type.startswith("image/"):
            asset_url = ""

        return {
            "id": event.get("id", ""),
            "title": title,
            "link": link,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "published_at": published_at,
            "site_tz": site_tz,
            "location": location,
            "map_link": map_link,
            "tags": tags,
            "categories": categories,
            "excerpt": excerpt,
            "body": body,
            "image_url": asset_url,
            "image_mime_type": content_type if asset_url else None,
        }

    @staticmethod
    def _sanitize_body(html: str) -> str:
        """Extract human-written content from Squarespace layout HTML.

        Squarespace wraps body content in sqs-layout grid scaffolding with
        embedded <style> blocks. This pulls out just the .sqs-html-content
        divs (the actual text/links), strips <style> and <script> tags, and
        falls back to the raw HTML if none are found.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        content_divs = soup.find_all("div", class_="sqs-html-content")
        if not content_divs:
            return html

        for div in content_divs:
            for tag in div.find_all(["style", "script"]):
                tag.decompose()

        return "\n".join(str(div) for div in content_divs)

    @staticmethod
    def _generate_id(event_data: dict[str, Any]) -> str:
        raw = f"{event_data['id']}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _build_content(event_data: dict[str, Any]) -> str:
        parts = []

        # Date / time
        date_str = _format_datetime_range(
            event_data["start_dt"], event_data.get("end_dt"), event_data.get("site_tz")
        )
        if date_str:
            parts.append(f"<p><strong>Date:</strong> {date_str}</p>")

        # Location
        if event_data.get("location"):
            loc = event_data["location"]
            if event_data.get("map_link"):
                loc = f'<a href="{event_data["map_link"]}">{loc}</a>'
            parts.append(f"<p><strong>Location:</strong> {loc}</p>")

        # Tags / categories
        if event_data.get("tags"):
            parts.append(
                f"<p><strong>Tags:</strong> {', '.join(event_data['tags'])}</p>"
            )
        if event_data.get("categories"):
            parts.append(
                f"<p><strong>Categories:</strong> {', '.join(event_data['categories'])}</p>"
            )

        # Body (primary human-written content)
        if event_data.get("body"):
            parts.append(event_data["body"])
        elif event_data.get("excerpt"):
            parts.append(event_data["excerpt"])

        # Link to details
        if event_data.get("link"):
            parts.append(
                f'<p><a href="{event_data["link"]}">View Event Details</a></p>'
            )

        return "\n".join(parts)


def _ms_to_utc(ms: int) -> datetime:
    """Convert a millisecond timestamp to a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _format_datetime_range(
    start: datetime, end: datetime | None, site_tz: str | None
) -> str:
    """Return a human-readable date/time range string."""
    from zoneinfo import ZoneInfo, available_timezones

    tz = None
    if site_tz:
        try:
            if site_tz in available_timezones():
                tz = ZoneInfo(site_tz)
        except Exception:
            pass

    if tz:
        local_start = start.astimezone(tz)
    else:
        local_start = start

    def _fmt(dt: datetime) -> str:
        # Build manually to avoid zero-padding issues with strftime
        weekday = dt.strftime("%A")
        month = dt.strftime("%B")
        day = str(dt.day)
        year = dt.strftime("%Y")
        hour = dt.hour
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p")
        # 12-hour format without leading zero
        hour_12 = hour % 12
        if hour_12 == 0:
            hour_12 = 12
        return f"{weekday}, {month} {day}, {year} at {hour_12}:{minute} {ampm}"

    result = _fmt(local_start)

    if end:
        if tz:
            local_end = end.astimezone(tz)
        else:
            local_end = end

        # If same day, just show end time
        if local_start.date() == local_end.date():
            hour = local_end.hour
            hour_12 = hour % 12
            if hour_12 == 0:
                hour_12 = 12
            end_str = f"{hour_12}:{local_end.strftime('%M')} {local_end.strftime('%p')}"
            result = f"{result} – {end_str}"
        else:
            result = f"{result} – {_fmt(local_end)}"

    if tz:
        result = f"{result} {local_start.tzname()}"

    return result


def _json_url(url: str) -> str:
    """Append Squarespace's JSON format query param if not already present."""
    if "format=json-pretty" not in url:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}format=json-pretty"
    return url
