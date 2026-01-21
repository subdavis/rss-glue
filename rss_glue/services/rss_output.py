"""RSS XML generation."""

from datetime import datetime, timezone

from feedgen.feed import FeedGenerator
from sqlmodel import Session

from rss_glue.feeds.registry import FeedRegistry
from rss_glue.models.db import Feed
from rss_glue.services.media_cache import expand_placeholders


def generate_rss(feed_id: str, session: Session, base_url: str) -> str:
    """Generate RSS XML for a feed."""
    feed = session.get(Feed, feed_id)
    if not feed:
        raise ValueError(f"Feed not found: {feed_id}")

    fg = FeedGenerator()
    fg.title(feed.name)
    fg.link(href=f"{base_url}feed/{feed_id}/rss", rel="self")
    fg.description(f"RSS feed: {feed.name}")
    fg.lastBuildDate(datetime.now(timezone.utc))

    # Get posts using the standardized get_posts method
    handler = FeedRegistry.get_handler(feed.type)
    posts = handler.get_posts(feed_id, feed.limit, session, base_url)

    for post in posts:
        entry = fg.add_entry()
        entry.title(post["title"])
        entry.link(href=post["link"])
        entry.guid(post["id"], permalink=False)

        if post.get("content"):
            # Expand placeholders to full URLs for RSS output
            content_with_urls = expand_placeholders(post["content"], base_url)
            entry.description(content_with_urls)

        if post.get("author"):
            entry.author(name=post["author"])

        # Ensure timezone awareness for feedgen
        pub_date = post["published_at"]
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        entry.pubDate(pub_date)

        # Add enclosures
        for enc in post.get("enclosures", []):
            # Expand placeholder URL if cached
            enc_url = expand_placeholders(enc["url"], base_url)
            entry.enclosure(
                url=enc_url,
                type=enc.get("mime_type") or "application/octet-stream",
                length=str(enc.get("length") or 0),
            )

    return fg.rss_str(pretty=True).decode("utf-8")
