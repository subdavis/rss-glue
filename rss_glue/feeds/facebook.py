"""Facebook feed handler using ScrapeCreators API."""
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlmodel import Session

from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import SystemConfig

logger = logging.getLogger(__name__)

SCRAPE_API_BASE = "https://api.scrapecreators.com/v1/facebook/group/posts"


@FeedRegistry.register("facebook")
class FacebookFeedHandler:
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
            logger.error(f"Facebook feed '{feed_id}': Missing scrape_creators_key in SystemConfig")
            return []

        try:
            with httpx.Client(timeout=30.0) as client:
                headers = {"x-api-key": api_key}
                params = {"url": url, "sort_by": "CHRONOLOGICAL"}
                response = client.get(SCRAPE_API_BASE, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("success"):
                    logger.warning(f"Facebook feed '{feed_id}': API returned unsuccessful status: {data}")
                    # Continue if posts are present? The v1 code returns if not success.
                    # Let's check if posts exist regardless, or respect success flag.
                    if not data.get("posts"):
                        return []

        except httpx.HTTPStatusError as e:
            logger.error(f"Facebook feed '{feed_id}': API error {e.response.status_code}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Facebook feed '{feed_id}': Request failed - {e}")
            return []

        posts = []
        # ScrapeCreators v1 structure: {"posts": [...]}
        items = data.get("posts", [])
        
        # Limit locally
        items = items[:limit]

        for item in items:
            # ID
            post_id = item.get("id")
            if not post_id:
                continue
            external_id = hashlib.sha256(str(post_id).encode()).hexdigest()[:16]

            # Timestamp
            publish_time = item.get("publishTime")
            if publish_time:
                published_at = datetime.fromtimestamp(publish_time, tz=timezone.utc).replace(tzinfo=None) # naive UTC
            else:
                published_at = datetime.utcnow()

            # Author
            author_data = item.get("author")
            author_name = "Facebook User"
            if isinstance(author_data, dict):
                author_name = author_data.get("name", author_name)
            
            # Text/Title
            text = item.get("text", "")
            title = text.split("\n")[0][:100] if text else "Facebook Post"
            
            # Link
            post_url = item.get("url", url)

            # Content Generation
            content = f"<p>{text}</p>" if text else ""
            
            # Images
            # 'images' is a list of urls, or 'image' is a single url
            images = item.get("images", [])
            if not images and item.get("image"):
                images = [item.get("image")]
            
            for img_url in images:
                if img_url:
                    content += f'<p><img src="{img_url}" /></p>'
            
            # Video
            if video_details := item.get("videoDetails"):
                # Usually has thumbnail
                thumb = video_details.get("thumbnail") or item.get("image")
                content += f'<p><a href="{post_url}">Watch Video</a></p>'
                if thumb:
                    content += f'<p><img src="{thumb}" alt="Video thumbnail" /></p>'

            posts.append({
                "external_id": external_id,
                "title": title,
                "content": content,
                "link": post_url,
                "author": author_name,
                "published_at": published_at,
            })

        return posts
