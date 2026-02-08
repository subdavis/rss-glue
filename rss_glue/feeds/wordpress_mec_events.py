"""WordPress Modern Events Calendar (MEC) feed handler."""

import hashlib
import html
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup
from pydantic import Field
from sqlmodel import Session

from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.models.db import Feed
from rss_glue.models.feed_config import FeedConfigBase


@FeedRegistry.register("wordpress_mec_events")
class WordPressMecEventsFeedHandler(BaseFeedHandler):
    """Handler for WordPress pages with Modern Events Calendar plugin.

    Extracts events from rendered HTML and filters out recurring events
    (those appearing multiple times on the page).
    """

    class Config(FeedConfigBase):
        """Configuration for a WordPress MEC Events source feed."""

        type: Literal["wordpress_mec_events"]
        url: str = Field(..., pattern=r"^https?://")
        recurring_threshold: int = Field(default=3, ge=1)

        @classmethod
        def sample_config(cls) -> dict:
            return cls._sample(
                type="wordpress_mec_events",
                url="https://www.example.com/wp-json/wp/v2/pages/123",
                recurring_threshold=3,
            )

        @classmethod
        def db_hydrate(cls, feed: Feed, session: Session | None = None, **kwargs):
            """Return any additional fields needed for DB storage."""
            return super().db_hydrate(
                feed,
                session=session,
                url=feed.config.get("url", ""),
                recurring_threshold=feed.config.get("recurring_threshold", 3),
                **kwargs,
            )

        def extra_config(self) -> dict:
            """Return any additional config fields needed for DB storage."""
            return {
                **super().extra_config(),
                "url": self.url,
                "recurring_threshold": self.recurring_threshold,
            }

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch and parse events from WordPress MEC page."""
        url = config["url"]
        limit = config.get("limit", 100)
        recurring_threshold = config.get("recurring_threshold", 3)

        # Fetch WordPress REST API response
        headers = {"User-Agent": "RSS-Glue/2.0 (Feed Aggregator)"}
        response = httpx.get(url, timeout=30.0, headers=headers)
        response.raise_for_status()
        data = response.json()

        # Extract rendered HTML content
        html_content = data.get("content", {}).get("rendered", "")
        if not html_content:
            return []

        soup = BeautifulSoup(html_content, "html.parser")

        # Find all event articles
        event_articles = soup.find_all("article", class_="mec-event-article")
        if not event_articles:
            return []

        # First pass: count title occurrences to identify recurring events
        title_counts: Counter[str] = Counter()
        for article in event_articles:
            title_elem = article.find(class_="mec-event-title")
            if title_elem:
                title_link = title_elem.find("a")
                if title_link:
                    title = title_link.get_text(strip=True)
                    title_counts[title] += 1

        # Build exclusion set for recurring events
        recurring_titles = {
            title
            for title, count in title_counts.items()
            if count >= recurring_threshold
        }

        # Second pass: extract non-recurring events
        posts = []
        seen_ids: set[str] = set()
        now = datetime.now(timezone.utc)

        for article in event_articles:
            event_data = WordPressMecEventsFeedHandler._parse_event(article)
            if not event_data:
                continue

            # Skip recurring events
            if event_data["title"] in recurring_titles:
                continue

            # Generate stable external ID
            external_id = WordPressMecEventsFeedHandler._generate_id(event_data)

            # Skip duplicates (same event appearing multiple times on page)
            if external_id in seen_ids:
                continue
            seen_ids.add(external_id)

            # Build content HTML
            content = WordPressMecEventsFeedHandler._build_content(event_data)

            # Build enclosures for event image
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
                    "published_at": now,  # Discovery time
                    "enclosures": enclosures,
                }
            )

            if len(posts) >= limit:
                break

        return posts

    @staticmethod
    def _parse_event(article: Any) -> dict[str, Any] | None:
        """Parse a single event article element."""
        # Get title and link
        title_elem = article.find(class_="mec-event-title")
        if not title_elem:
            return None

        title_link = title_elem.find("a")
        if not title_link:
            return None

        title = title_link.get_text(strip=True)
        link = title_link.get("href", "")

        # Get event ID from data attribute
        event_id = title_link.get("data-event-id", "")

        # Get date (first text node in the date element, not the time div)
        date_elem = article.find(class_="mec-event-date")
        date_text = ""
        if date_elem:
            # Get just the direct text content, not child elements
            for child in date_elem.children:
                if isinstance(child, str):
                    text = child.strip()
                    if text:
                        date_text = " ".join(text.split())
                        break

        # Get time range
        time_range = ""
        start_time = article.find(class_="mec-start-time")
        end_time = article.find(class_="mec-end-time")
        if start_time:
            time_range = start_time.get_text(strip=True)
            if end_time:
                time_range += f" - {end_time.get_text(strip=True)}"

        # Get location
        location_elem = article.find(class_="mec-grid-event-location")
        location = location_elem.get_text(strip=True) if location_elem else ""

        # Get categories
        categories = []
        cat_list = article.find(class_="mec-categories")
        if cat_list:
            for cat in cat_list.find_all("a"):
                categories.append(cat.get_text(strip=True))

        # Get image URL
        image_url = ""
        image_elem = article.find(class_="mec-event-image")
        if image_elem:
            img = image_elem.find("img")
            if img:
                image_url = img.get("src", "")

        return {
            "event_id": event_id,
            "title": html.unescape(title),
            "link": link,
            "date": date_text,
            "time_range": time_range,
            "location": location,
            "categories": categories,
            "image_url": image_url,
        }

    @staticmethod
    def _generate_id(event_data: dict[str, Any]) -> str:
        """Generate a stable external ID for an event."""
        # Use event_id if available, otherwise hash title + date
        if event_data.get("event_id"):
            raw_id = f"{event_data['event_id']}-{event_data['title']}"
        else:
            raw_id = f"{event_data['title']}-{event_data['date']}"
        return hashlib.sha256(raw_id.encode()).hexdigest()[:16]

    @staticmethod
    def _build_content(event_data: dict[str, Any]) -> str:
        """Build HTML content for an event post."""
        parts = []

        if event_data.get("date"):
            date_str = event_data["date"]
            if event_data.get("time_range"):
                date_str += f" ({event_data['time_range']})"
            parts.append(f"<p><strong>Date:</strong> {date_str}</p>")

        if event_data.get("location"):
            parts.append(f"<p><strong>Location:</strong> {event_data['location']}</p>")

        if event_data.get("categories"):
            cats = ", ".join(event_data["categories"])
            parts.append(f"<p><strong>Categories:</strong> {cats}</p>")

        if event_data.get("link"):
            parts.append(
                f'<p><a href="{event_data["link"]}">View Event Details</a></p>'
            )

        return "\n".join(parts)
