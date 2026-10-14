"""Instagram feed handler using ScrapeCreators API."""

import hashlib
import logging
import re
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


def _published_at(item: dict) -> datetime | None:
    """Post time, trying every shape the API has returned, else None.

    The "XIGPolaris*" response shape (current as of 2026-10) dropped taken_at
    and nulls created_at, but the date survives in accessibility_caption:
    "Photo by Some Name on September 07, 2026."

    There is deliberately no "now" fallback - a fabricated date silently
    reorders the feed and cannot be corrected later, because stored posts are
    never re-dated. The caller fails the fetch instead.
    """
    if taken_at := item.get("taken_at"):
        return datetime.fromtimestamp(taken_at, tz=timezone.utc)
    if created_at := item.get("created_at"):
        try:
            return datetime.fromisoformat(
                str(created_at).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            pass
    if match := re.search(
        r" on (\w+ \d{1,2}, \d{4})\.", item.get("accessibility_caption") or ""
    ):
        try:
            # Noon UTC: a date-only value must land on the right day in any
            # display timezone.
            return datetime.strptime(match.group(1), "%B %d, %Y").replace(
                hour=12, tzinfo=timezone.utc
            )
        except ValueError:
            pass
    return None


def _image_url(media: dict) -> str | None:
    """Best image for a post or a carousel child, across response shapes."""
    candidates = (media.get("image_versions2") or {}).get("candidates") or []
    if candidates:
        return candidates[0].get("url")
    return media.get("display_uri")


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
            # Anything missing below is upstream breakage, and every degraded
            # value we could substitute writes permanent garbage into the DB:
            # a different id seed re-posts the whole feed as duplicates, and a
            # fabricated date cannot be corrected on a later fetch. Fail the
            # whole fetch instead - update_feed() records the error and disables
            # the feed, which is noisy but recoverable.

            # ID - derived from the media pk and user pk rather than item["id"],
            # whose format the API has changed under us (it was "{pk}_{user_pk}",
            # now "POLARIS_{pk}").
            pk = item.get("pk") or item.get("id")
            user = item.get("user") or {}
            user_pk = user.get("pk")
            if not pk or not user_pk:
                raise ValueError(
                    f"Instagram feed '{feed_id}': item has no pk/user.pk, "
                    f"cannot build a stable id - keys: {sorted(item)}"
                )
            external_id = hashlib.sha256(f"{pk}_{user_pk}".encode()).hexdigest()[:16]

            # Timestamp
            published_at = _published_at(item)
            if published_at is None:
                raise ValueError(
                    f"Instagram feed '{feed_id}': post {pk} has no usable date "
                    f"(taken_at, created_at, accessibility_caption all unusable) "
                    f"- keys: {sorted(item)}"
                )

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

            # Engagement metrics - None (not 0) when the API omits them, so an
            # existing post's score is not clobbered on re-fetch
            like_count = item.get("like_count")
            comment_count = item.get("comment_count")

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

            # Images - carousel children when the API gives them, else the one
            # image it does give (image_versions2 candidate or display_uri)
            children = item.get("carousel_media") or [item]
            images = [url for media in children if (url := _image_url(media))]
            is_video = bool(item.get("video_versions") or item.get("video_url"))
            carousel_count = item.get("carousel_media_count") or len(images)
            if not images and not is_video:
                raise ValueError(
                    f"Instagram feed '{feed_id}': post {pk} has no image or "
                    f"video media - keys: {sorted(item)}"
                )

            # Render content using Jinja template
            content_template = templates.env.get_template("feeds/instagram.html")
            content = content_template.render(
                caption_text=caption_text,
                images=images,
                is_video=is_video,
                carousel_count=carousel_count,
                link=link,
                like_count=like_count,
                comment_count=comment_count,
                music_info=music_info,
            )

            # Author
            author = f"@{user.get('username', username)}"

            posts.append(
                {
                    "external_id": external_id,
                    "title": title,
                    "content": content,
                    "link": link,
                    "author": author,
                    "published_at": published_at,
                    "score": float(like_count) if like_count is not None else None,
                }
            )

        return posts
