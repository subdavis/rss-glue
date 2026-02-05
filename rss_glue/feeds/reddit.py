"""Reddit feed handler."""

import html
from datetime import datetime, timezone
from typing import Any

from markupsafe import Markup
from sqlmodel import Session

from rss_glue.feeds.http_client import create_client
from rss_glue.feeds.registry import BaseFeedHandler, FeedRegistry
from rss_glue.templates import templates


def deep_get(d: dict | None, *keys) -> Any:
    """Safely get nested dict values, returning None if any key is missing or value is None."""
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d


@FeedRegistry.register("reddit")
class RedditFeedHandler(BaseFeedHandler):
    """Handler for Reddit feeds using their JSON API."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch and parse Reddit feed."""
        subreddit = config["subreddit"]
        listing_type = config.get("listing_type", "top")
        time_filter = config.get("time_filter", "day")
        limit = config.get("limit", 20)

        url = f"https://www.reddit.com/r/{subreddit}/{listing_type}.json"
        params = {"limit": limit}
        if listing_type == "top":
            params["t"] = time_filter

        # Use robust HTTP client with Reddit-specific User-Agent
        with create_client(
            extra_headers={"User-Agent": "rss-glue/2.0.0 (Feed Aggregator)"}
        ) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        posts = []

        children = data.get("data", {}).get("children", [])

        for child in children:
            item = child.get("data", {})
            if not item:
                continue

            external_id = item.get("id") or item.get("name")
            title = item.get("title", "Untitled")

            # Score (from v1)
            score = item.get("score", 1)

            # Content construction with post_hint handling
            post_hint = item.get("post_hint", "")
            url_val = item.get("url", "")
            selftext_html = item.get("selftext_html")
            permalink = item.get("permalink")
            post_link = f"https://www.reddit.com{permalink}" if permalink else url_val

            # Extract oembed data for rich videos
            oembed = deep_get(item, "media", "oembed")
            oembed_html = None
            oembed_thumbnail = None
            if oembed:
                raw_oembed_html = oembed.get("html", "")
                if raw_oembed_html:
                    oembed_html = Markup(html.unescape(raw_oembed_html))
                else:
                    oembed_thumbnail = oembed.get("thumbnail_url")

            # Extract hosted video fallback URL
            video_fallback_url = deep_get(item, "media", "reddit_video", "fallback_url")

            # Decode selftext HTML
            decoded_selftext = None
            if selftext_html:
                decoded_selftext = Markup(html.unescape(selftext_html))

            num_comments = item.get("num_comments", 0)

            # Render content using Jinja template
            content_template = templates.env.get_template("feeds/reddit.html")
            content = content_template.render(
                post_hint=post_hint,
                url=url_val,
                post_link=post_link,
                oembed_html=oembed_html,
                oembed_thumbnail=oembed_thumbnail,
                video_fallback_url=video_fallback_url,
                selftext_html=decoded_selftext,
                score=score,
                num_comments=num_comments,
            )

            author = item.get("author", "unknown")

            created_utc = item.get("created_utc")
            published_at = (
                datetime.fromtimestamp(created_utc, timezone.utc)
                if created_utc
                else datetime.now(timezone.utc)
            )

            posts.append(
                {
                    "external_id": external_id,
                    "title": title,
                    "content": content,
                    "link": post_link,
                    "author": author,
                    "published_at": published_at,
                    "score": float(score),  # Score field for sorting
                }
            )

        return posts
