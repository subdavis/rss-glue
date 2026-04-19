"""Squarespace Events feed handler."""

import hashlib
import html
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup, NavigableString
from pydantic import Field
from sqlmodel import Session

from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.models.feed_config import FeedConfigBase


@FeedRegistry.register("squarespace_events")
class SquarespaceEventsFeedHandler(BaseFeedHandler):
    """Handler for Squarespace event listing pages.

    Parses the standard Squarespace event list template, which uses
    consistent CSS class names across all Squarespace sites.
    """

    class Config(FeedConfigBase):
        """Configuration for a Squarespace Events source feed."""

        type: Literal["squarespace_events"]
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
        """Fetch and parse events from a Squarespace events page."""
        url = config["url"]
        limit = config.get("limit", 100)
        include_past = config.get("include_past", False)

        headers = {"User-Agent": "RSS-Glue/2.0 (Feed Aggregator)"}
        response = httpx.get(url, timeout=30.0, headers=headers, follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("article", class_="eventlist-event")
        if not articles:
            return []

        posts = []
        seen_ids: set[str] = set()

        for article in articles:
            if not include_past and "eventlist-event--past" in article.get("class", []):
                continue

            event_data = SquarespaceEventsFeedHandler._parse_event(article)
            if not event_data:
                continue

            external_id = SquarespaceEventsFeedHandler._generate_id(event_data)
            if external_id in seen_ids:
                continue
            seen_ids.add(external_id)

            published_at = SquarespaceEventsFeedHandler._parse_date(
                event_data.get("iso_date", "")
            )
            content = SquarespaceEventsFeedHandler._build_content(event_data)

            enclosures = []
            if event_data.get("image_url"):
                enclosures.append(
                    {
                        "url": event_data["image_url"],
                        "mime_type": "image/jpeg",
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
                    "published_at": published_at,
                    "enclosures": enclosures,
                }
            )

            if len(posts) >= limit:
                break

        return posts

    @staticmethod
    def _parse_event(article: Any) -> dict[str, Any] | None:
        """Parse a single Squarespace event article element."""
        # Title and link
        title_link = article.find("a", class_="eventlist-title-link")
        if not title_link:
            return None

        title = html.unescape(title_link.get_text(strip=True))
        link = title_link.get("href", "")
        # Make relative URLs absolute (Squarespace links are usually absolute)
        if link and not link.startswith("http"):
            link = link  # leave as-is; could be resolved with base URL if needed

        # Machine-readable date
        date_elem = article.find("time", class_="event-date")
        iso_date = date_elem.get("datetime", "") if date_elem else ""
        display_date = date_elem.get_text(strip=True) if date_elem else ""

        # Time range
        start_time_elem = article.find("time", class_="event-time-localized-start")
        end_time_elem = article.find("time", class_="event-time-localized-end")
        start_time = start_time_elem.get_text(strip=True) if start_time_elem else ""
        end_time = end_time_elem.get_text(strip=True) if end_time_elem else ""

        # Location: extract venue name from text nodes (excluding the map link text)
        location = ""
        map_link = ""
        address_elem = article.find("li", class_="eventlist-meta-address")
        if address_elem:
            text_parts = [
                c.strip()
                for c in address_elem.children
                if isinstance(c, NavigableString) and c.strip()
            ]
            location = " ".join(text_parts)
            map_anchor = address_elem.find("a", class_="eventlist-meta-address-maplink")
            if map_anchor:
                map_link = map_anchor.get("href", "")

        # Description
        description = ""
        excerpt_elem = article.find(class_="eventlist-excerpt")
        if excerpt_elem:
            p = excerpt_elem.find("p")
            description = (
                p.get_text(strip=True) if p else excerpt_elem.get_text(strip=True)
            )

        # Image: prefer data-src, fall back to src
        image_url = ""
        thumbnail = article.find(class_="eventlist-column-thumbnail")
        img = thumbnail.find("img") if thumbnail else article.find("img")
        if img:
            image_url = img.get("data-src") or img.get("src", "")

        return {
            "title": title,
            "link": link,
            "iso_date": iso_date,
            "display_date": display_date,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
            "map_link": map_link,
            "description": description,
            "image_url": image_url,
        }

    @staticmethod
    def _generate_id(event_data: dict[str, Any]) -> str:
        raw = f"{event_data['title']}-{event_data['iso_date']}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _parse_date(iso_date: str) -> datetime:
        try:
            return datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)

    @staticmethod
    def _build_content(event_data: dict[str, Any]) -> str:
        parts = []

        if event_data.get("display_date"):
            date_str = event_data["display_date"]
            times = []
            if event_data.get("start_time"):
                times.append(event_data["start_time"])
            if event_data.get("end_time"):
                times.append(event_data["end_time"])
            if times:
                date_str += f" ({' – '.join(times)})"
            parts.append(f"<p><strong>Date:</strong> {date_str}</p>")

        if event_data.get("location"):
            loc = event_data["location"]
            if event_data.get("map_link"):
                loc = f'<a href="{event_data["map_link"]}">{loc}</a>'
            parts.append(f"<p><strong>Location:</strong> {loc}</p>")

        if event_data.get("description"):
            parts.append(
                f"<p><strong>Description:</strong> {event_data['description']}</p>"
            )

        if event_data.get("link"):
            parts.append(
                f'<p><a href="{event_data["link"]}">View Event Details</a></p>'
            )

        return "\n".join(parts)
