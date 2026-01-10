"""Instagram feed handler using ScrapeCreators API."""
import hashlib
import logging
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import Session

from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import SystemConfig

logger = logging.getLogger(__name__)

SCRAPE_API_BASE = "https://api.scrapecreators.com/v2/instagram/user/posts"


@FeedRegistry.register("instagram")
class InstagramFeedHandler:
    """Handler for Instagram feeds using ScrapeCreators API."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch posts from Instagram via ScrapeCreators.

        Args:
            feed_id: The feed identifier
            config: Configuration containing username
            session: Database session

        Returns:
            List of post dicts
        """
        username = config.get("username")
        limit = config.get("limit", 20)

        if not username:
            logger.error(f"Instagram feed '{feed_id}': Missing username")
            return []

        # Get global API key
        key_entry = session.get(SystemConfig, "scrape_creators_key")
        api_key = key_entry.value if key_entry else None

        if not api_key:
            logger.error(f"Instagram feed '{feed_id}': Missing scrape_creators_key in SystemConfig")
            return []

        try:
            with httpx.Client(timeout=30.0) as client:
                headers = {"x-api-key": api_key}
                params = {"handle": username}
                response = client.get(SCRAPE_API_BASE, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Instagram feed '{feed_id}': API error {e.response.status_code}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Instagram feed '{feed_id}': Request failed - {e}")
            return []

        posts = []
        # ScrapeCreators v2 structure: {"items": [...]}
        items = data.get("items", [])

        # Limit locally since API doesn't seem to support limit param in v1 code (it wasn't used)
        # But we should respect the configured limit
        items = items[:limit]

        for item in items:
            # ID
            pk = item.get("id") or item.get("pk")
            if not pk:
                continue
            external_id = hashlib.sha256(str(pk).encode()).hexdigest()[:16]

            # Timestamp
            taken_at = item.get("taken_at")
            if taken_at:
                published_at = datetime.utcfromtimestamp(taken_at)
            else:
                published_at = datetime.utcnow()

            # Link
            code = item.get("code")
            link = f"https://www.instagram.com/p/{code}/" if code else f"https://www.instagram.com/{username}"

            # Caption/Title
            caption_dict = item.get("caption")
            caption_text = caption_dict.get("text", "") if caption_dict else ""
            title = caption_text.split("\n")[0][:100] if caption_text else "Instagram Post"

            # Content generation
            content = f"<p>{caption_text}</p>" if caption_text else ""
            
            # Images/Video
            # Check for carousel
            if carousel_media := item.get("carousel_media"):
                for media in carousel_media:
                    if image_versions := media.get("image_versions2", {}).get("candidates"):
                        # Get largest image (usually first or determined by resolution)
                        img_url = image_versions[0].get("url")
                        if img_url:
                            content += f'<p><img src="{img_url}" /></p>'
            # Check for single video/image
            elif item.get("media_type") == 2 and (video_versions := item.get("video_versions")):
                # Video
                # Try to find poster
                poster_url = ""
                if image_versions := item.get("image_versions2", {}).get("candidates"):
                    poster_url = image_versions[0].get("url")
                
                content += f'<p><a href="{link}">Watch Video</a></p>'
                if poster_url:
                    content += f'<p><img src="{poster_url}" alt="Video thumbnail" /></p>'
            elif image_versions := item.get("image_versions2", {}).get("candidates"):
                # Single Image
                img_url = image_versions[0].get("url")
                if img_url:
                    content += f'<p><img src="{img_url}" /></p>'

            # Author
            user = item.get("user", {})
            author = f"@{user.get('username', username)}"

            posts.append({
                "external_id": external_id,
                "title": title,
                "content": content,
                "link": link,
                "author": author,
                "published_at": published_at,
            })

        return posts
