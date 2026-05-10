"""Instagram feed handler using ScrapeCreators API."""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from markupsafe import Markup
from pydantic import Field
from sqlmodel import Session

from rss_glue.feeds.http_client import create_client
from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.models.db import SystemConfig
from rss_glue.models.feed_config import FeedConfigBase
from rss_glue.templates import templates

logger = logging.getLogger(__name__)

SCRAPE_API_BASE = "https://api.scrapecreators.com/v2/instagram/user/posts"


@FeedRegistry.register("instagram")
class InstagramFeedHandler(BaseFeedHandler):
    """Handler for Instagram feeds using ScrapeCreators API."""

    class Config(FeedConfigBase):
        """Configuration for an Instagram source feed."""

        type: Literal["instagram"]
        username: str = Field(..., min_length=1)

        def extra_config(self) -> dict:
            """Return any additional config fields needed for DB storage."""
            return {
                **super().extra_config(),
                "username": self.username,
            }

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
            logger.error(
                f"Instagram feed '{feed_id}': Missing scrape_creators_key in SystemConfig"
            )
            return []

        try:
            with create_client(
                timeout=30.0, extra_headers={"x-api-key": api_key}
            ) as client:
                params = {"handle": username}
                response = client.get(SCRAPE_API_BASE, params=params)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            logger.error(f"Instagram feed '{feed_id}': Request failed - {e}")
            return []

        posts = []
        items = data.get("items", [])
        items = items[:limit]

        for item in items:
            # ID
            pk = item.get("id") or item.get("pk")
            if not pk:
                continue
            external_id = hashlib.sha256(str(pk).encode()).hexdigest()[:16]

            # Timestamp - use timezone-aware datetime
            taken_at = item.get("taken_at")
            if taken_at:
                published_at = datetime.fromtimestamp(taken_at, tz=timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)

            # Link
            code = item.get("code")
            link = (
                f"https://www.instagram.com/p/{code}/"
                if code
                else f"https://www.instagram.com/{username}"
            )

            # Caption/Title
            caption_dict = item.get("caption")
            caption_text = caption_dict.get("text", "") if caption_dict else ""
            title = (
                caption_text.split("\n")[0][:100] if caption_text else "Instagram Post"
            )

            # Engagement metrics
            like_count = item.get("like_count", 0)
            comment_count = item.get("comment_count", 0)

            # Music info extraction (from v1)
            music_info = None
            if music_metadata := item.get("music_metadata"):
                if music_info_data := music_metadata.get("music_info"):
                    if music_asset_info := music_info_data.get("music_asset_info"):
                        music_title = music_asset_info.get("title")
                        artist = music_asset_info.get("display_artist")
                        if music_title and artist:
                            music_info = Markup("{} - {}").format(music_title, artist)
                        elif music_title:
                            music_info = Markup("{}").format(music_title)

            # Images/Video - collect data for template
            carousel_images = []
            is_video = False
            video_poster = None
            single_image = None

            if carousel_media := item.get("carousel_media"):
                for media in carousel_media:
                    if image_versions := media.get("image_versions2", {}).get(
                        "candidates"
                    ):
                        img_url = image_versions[0].get("url")
                        if img_url:
                            carousel_images.append(img_url)
            elif item.get("media_type") == 2 and item.get("video_versions"):
                # Video - add poster image
                is_video = True
                if image_versions := item.get("image_versions2", {}).get("candidates"):
                    video_poster = image_versions[0].get("url")
            elif image_versions := item.get("image_versions2", {}).get("candidates"):
                single_image = image_versions[0].get("url")

            # Render content using Jinja template
            content_template = templates.env.get_template("feeds/instagram.html")
            content = content_template.render(
                caption_text=caption_text,
                carousel_images=carousel_images,
                is_video=is_video,
                video_poster=video_poster,
                single_image=single_image,
                link=link,
                like_count=like_count,
                comment_count=comment_count,
                music_info=music_info,
            )

            # Author
            user = item.get("user", {})
            author = f"@{user.get('username', username)}"

            posts.append(
                {
                    "external_id": external_id,
                    "title": title,
                    "content": content,
                    "link": link,
                    "author": author,
                    "published_at": published_at,
                    "score": float(like_count),  # Use like count as score
                }
            )

        return posts
