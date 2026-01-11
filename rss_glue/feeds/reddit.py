"""Reddit feed handler."""

import html
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session

from rss_glue.feeds.http_client import create_client
from rss_glue.feeds.registry import FeedRegistry


@FeedRegistry.register("reddit")
class RedditFeedHandler:
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
            extra_headers={"User-Agent": "rss-glue/2.0.0 (by /u/rss-glue-bot)"}
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

            content_parts = []

            # Handle different post types based on post_hint
            if post_hint == "image":
                content_parts.append(f'<p><img src="{url_val}" alt="image" /></p>')
            elif post_hint == "rich:video":
                # Handle oembed for rich videos (from v1)
                oembed = item.get("media", {}).get("oembed")
                if oembed:
                    oembed_html = oembed.get("html", "")
                    if oembed_html:
                        content_parts.append(html.unescape(oembed_html))
                    elif oembed.get("thumbnail_url"):
                        content_parts.append(
                            f'<p><img src="{oembed.get("thumbnail_url")}" alt="video thumbnail" /></p>'
                        )
                        content_parts.append(
                            f'<p><a href="{url_val}">Watch Video</a></p>'
                        )
                else:
                    content_parts.append(f'<p><a href="{url_val}">Watch Video</a></p>')
            elif post_hint == "hosted:video":
                # Handle hosted videos with fallback URL (from v1)
                fallback_url = (
                    item.get("media", {}).get("reddit_video", {}).get("fallback_url")
                )
                if fallback_url:
                    content_parts.append(
                        f'<p><video controls src="{fallback_url}"></video></p>'
                    )
                else:
                    content_parts.append(f'<p><a href="{url_val}">Watch Video</a></p>')
            elif post_hint == "link":
                content_parts.append(f'<p><a href="{url_val}">{url_val}</a></p>')
            elif url_val and url_val != post_link:
                # External link
                content_parts.append(f'<p><a href="{url_val}">{url_val}</a></p>')

            # Add selftext if present
            if selftext_html:
                decoded_html = html.unescape(selftext_html)
                content_parts.append(decoded_html)

            # Add score and metadata
            num_comments = item.get("num_comments", 0)
            content_parts.append(
                f"<p><small>⬆️ {score:,} points | 💬 {num_comments:,} comments</small></p>"
            )

            content = "\n".join(content_parts)

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
