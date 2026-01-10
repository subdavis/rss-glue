"""Reddit feed handler."""
import html
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlmodel import Session

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

        headers = {
            "User-Agent": "rss-glue/2.0.0 (by /u/rss-glue-bot)",
        }

        with httpx.Client() as client:
            response = client.get(url, params=params, headers=headers, follow_redirects=True)
            response.raise_for_status()
            data = response.json()

        posts = []
        
        # Reddit JSON structure:
        # data -> children -> [ { data: { ... } }, ... ]
        children = data.get("data", {}).get("children", [])
        
        for child in children:
            item = child.get("data", {})
            if not item:
                continue

            # Skip sticky posts if we want? The config didn't specify. 
            # Let's keep them for now, or maybe the user wants them.
            
            external_id = item.get("id") or item.get("name")
            title = item.get("title", "Untitled")
            
            # Construct content
            # Could be selftext (markdown) or a link to image/article
            post_hint = item.get("post_hint", "")
            url_val = item.get("url", "")
            selftext = item.get("selftext_html")  # Use HTML if available
            
            content_parts = []
            
            if url_val and url_val != f"https://www.reddit.com{item.get('permalink')}":
                # External link or image
                if post_hint == "image":
                    content_parts.append(f'<p><img src="{url_val}" alt="image" /></p>')
                else:
                    content_parts.append(f'<p><a href="{url_val}">{url_val}</a></p>')
            
            if selftext:
                # selftext_html is usually escaped
                decoded_html = html.unescape(selftext)
                content_parts.append(decoded_html)
            
            content = "\n".join(content_parts)
            
            permalink = item.get("permalink")
            link = f"https://www.reddit.com{permalink}" if permalink else url_val
            
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
                    "link": link,
                    "author": author,
                    "published_at": published_at,
                }
            )

        return posts
