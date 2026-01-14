"""Facebook feed handler using ScrapeCreators API."""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session

from rss_glue.feeds.http_client import create_client
from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.models.db import SystemConfig
from rss_glue.templates import templates

logger = logging.getLogger(__name__)

SCRAPE_API_BASE = "https://api.scrapecreators.com/v1/facebook/group/posts"


@FeedRegistry.register("facebook")
class FacebookFeedHandler(BaseFeedHandler):
    """Handler for Facebook Page/Group feeds using ScrapeCreators API."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch posts from Facebook via ScrapeCreators.

        Args:
            feed_id: The feed identifier
            config: Configuration containing url
            session: Database session

        Returns:
            List of post dicts
        """
        url = config.get("url")
        limit = config.get("limit", 20)

        if not url:
            logger.error(f"Facebook feed '{feed_id}': Missing url")
            return []

        # Get global API key
        key_entry = session.get(SystemConfig, "scrape_creators_key")
        api_key = key_entry.value if key_entry else None

        if not api_key:
            logger.error(
                f"Facebook feed '{feed_id}': Missing scrape_creators_key in SystemConfig"
            )
            return []

        try:
            with create_client(
                timeout=30.0, extra_headers={"x-api-key": api_key}
            ) as client:
                params = {"url": url, "sort_by": "CHRONOLOGICAL"}
                response = client.get(SCRAPE_API_BASE, params=params)
                response.raise_for_status()
                data = response.json()

                if not data.get("success"):
                    logger.warning(
                        f"Facebook feed '{feed_id}': API returned unsuccessful status: {data}"
                    )
                    if not data.get("posts"):
                        return []

        except Exception as e:
            logger.error(f"Facebook feed '{feed_id}': Request failed - {e}")
            return []

        posts = []
        items = data.get("posts", [])
        items = items[:limit]

        for item in items:
            # ID
            post_id = item.get("id")
            if not post_id:
                continue
            external_id = hashlib.sha256(str(post_id).encode()).hexdigest()[:16]

            # Timestamp - timezone-aware
            publish_time = item.get("publishTime")
            if publish_time:
                published_at = datetime.fromtimestamp(publish_time, tz=timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)

            # Author
            author_data = item.get("author")
            author_name = "Facebook User"
            if isinstance(author_data, dict):
                author_name = author_data.get("name", author_name)

            # Text/Title with fallbacks for Photo/Video posts (from v1)
            text = item.get("text", "")
            if text:
                title = text.split("\n")[0][:100]
            elif item.get("image") or item.get("images"):
                title = "Photo Post"
            elif item.get("videoDetails"):
                title = "Video Post"
            else:
                title = "Facebook Group Post"

            # Link
            post_url = item.get("url", url)

            # Engagement metrics (from v1)
            reaction_count = item.get("reactionCount", 0)
            comment_count = item.get("commentCount", 0)
            video_view_count = item.get("videoViewCount")

            # Images
            images = item.get("images", [])
            if not images and item.get("image"):
                images = [item.get("image")]

            # Video
            video_details = item.get("videoDetails")
            video_thumbnail = None
            if video_details:
                video_thumbnail = video_details.get("thumbnailUrl") or item.get("image")

            # Render content using Jinja template
            content_template = templates.env.get_template("feeds/facebook.html")
            content = content_template.render(
                text=text,
                images=images,
                video_details=video_details,
                video_thumbnail=video_thumbnail,
                post_url=post_url,
                reaction_count=reaction_count,
                comment_count=comment_count,
                video_view_count=video_view_count,
            )

            posts.append(
                {
                    "external_id": external_id,
                    "title": title,
                    "content": content,
                    "link": post_url,
                    "author": author_name,
                    "published_at": published_at,
                    "score": float(reaction_count),  # Use reaction count as score
                }
            )

        return posts
