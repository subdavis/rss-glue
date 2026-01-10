"""HackerNews feed handler."""
import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import Session

from rss_glue.feeds.registry import FeedRegistry

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"

STORY_ENDPOINTS = {
    "top": "/topstories.json",
    "new": "/newstories.json",
    "best": "/beststories.json",
}


@FeedRegistry.register("hackernews")
class HackerNewsFeedHandler:
    """Handler for HackerNews feeds."""

    @staticmethod
    def fetch(feed_id: str, config: dict[str, Any], session: Session) -> list[dict]:
        """Fetch stories from HackerNews API."""
        story_type = config.get("story_type", "top")
        limit = config.get("limit", 30)

        if story_type not in STORY_ENDPOINTS:
            logger.error(f"Invalid story_type '{story_type}', using 'top'")
            story_type = "top"

        # Run async fetching in sync context
        return asyncio.run(_fetch_stories(story_type, limit))


async def _fetch_stories(story_type: str, limit: int) -> list[dict]:
    """Async fetch of HN stories."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch story IDs
        endpoint = STORY_ENDPOINTS[story_type]
        response = await client.get(f"{HN_API_BASE}{endpoint}")
        response.raise_for_status()
        story_ids = response.json()[:limit]

        if not story_ids:
            return []

        # Fetch items concurrently
        tasks = [_fetch_item(client, item_id) for item_id in story_ids]
        items = await asyncio.gather(*tasks, return_exceptions=True)

        posts = []
        for item in items:
            if isinstance(item, Exception):
                logger.warning(f"Failed to fetch HN item: {item}")
                continue
            if item is None:
                continue

            post = _item_to_post(item)
            if post:
                posts.append(post)

        return posts


async def _fetch_item(client: httpx.AsyncClient, item_id: int) -> dict | None:
    """Fetch a single HN item."""
    try:
        response = await client.get(f"{HN_API_BASE}/item/{item_id}.json")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch item {item_id}: {e}")
        return None


def _item_to_post(item: dict) -> dict | None:
    """Convert HN item to post dict."""
    if not item or item.get("deleted") or item.get("dead"):
        return None

    item_id = item.get("id")
    if not item_id:
        return None

    # Generate external_id from HN item ID
    external_id = hashlib.sha256(f"hn:{item_id}".encode()).hexdigest()[:16]

    # Parse time (Unix timestamp)
    timestamp = item.get("time")
    published_at = datetime.utcfromtimestamp(timestamp) if timestamp else datetime.utcnow()

    # Build content from text or URL
    title = item.get("title", "Untitled")
    url = item.get("url")
    text = item.get("text", "")

    # For stories with URL, link to external; for Ask HN etc, link to HN
    if url:
        link = url
        content = f'<p><a href="{url}">{title}</a></p>'
        if text:
            content += f"\n{text}"
    else:
        link = f"https://news.ycombinator.com/item?id={item_id}"
        content = text if text else f'<p><a href="{link}">{title}</a></p>'

    # Add metadata
    score = item.get("score", 0)
    descendants = item.get("descendants", 0)
    hn_link = f"https://news.ycombinator.com/item?id={item_id}"
    content += f'\n<p><small>{score} points | <a href="{hn_link}">{descendants} comments</a></small></p>'

    return {
        "external_id": external_id,
        "title": title,
        "content": content,
        "link": link,
        "author": item.get("by"),
        "published_at": published_at,
    }
