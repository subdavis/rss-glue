from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import feedparser
import pytz

from rss_glue.feeds import feed
from rss_glue.resources import short_hash_string, utc_now


@dataclass
class RssPost(feed.FeedItem):
    feedparser_parsed: dict

    def render(self) -> str:
        entry = self.feedparser_parsed
        content = entry.get("content", [])
        html_content = ""

        for c in content:
            content_type = c.get("type", "text/plain")
            if content_type == "text/plain":
                html_content += f"<p>{c.get('value')}</p>"
            else:
                html_content += c.get("value")

        # For some reason, reddit likes to structure posts with <tables>
        # so we need to strip them out
        html_content = html_content.replace("<table>", "").replace("</table>", "")

        return html_content


class RssFeed(feed.ScheduleFeed):
    """
    RSS Feed source
    """

    id: str  # A unique identifier for this feed
    limit: int
    name = "rss"
    url: str

    def __init__(self, id: str, url: str, limit: int = 12, schedule: str = "0 * * * *"):
        self.url = url
        self.limit = limit
        self.id = id
        super().__init__(schedule=schedule)
        meta = self.meta
        self.title = meta.get("title", "RSS Feed")
        self.author = meta.get("author", "RSS Glue")
        self.origin_url = meta.get("link", "unknown")

    @property
    def namespace(self):
        return f"{self.name}_{self.id}"

    def update(self, force: bool = False):
        if not self.needs_update(force):
            return

        f = feedparser.parse(self.url)
        self.title = getattr(f.feed, "title", "RSS Feed")
        self.author = getattr(f.feed, "author", "RSS Glue")
        self.origin_url = getattr(f.feed, "link", self.url)
        self.meta = {
            "title": self.title,
            "author": self.author,
            "link": self.origin_url,
        }

        self.logger.debug(f"   found {len(f.entries)} posts")
        for entry in f.entries[: self.limit]:
            # The post ID might be an unsafe string, so we hash it
            # to make it safe for use as a filename
            id = getattr(entry, "id")
            post_id = short_hash_string(id)
            # Load the post from the cache
            post = self.cache_get(post_id)

            # If the post is already in the cache, skip it
            if post:
                self.logger.debug(f"   cache hit {post_id}")
                continue

            try:
                published_at = datetime.fromisoformat(entry.published)
            except:
                published_at_tuple = getattr(entry, "published_parsed", None)
                if published_at_tuple:
                    published_at = datetime(*published_at_tuple[:6], tzinfo=pytz.utc)  # type: ignore

            title = getattr(entry, "title", "RSS Post")
            value = RssPost(
                version=1,
                namespace=self.namespace,
                id=post_id,
                author=getattr(entry, "author", self.author),
                origin_url=getattr(entry, "link", self.origin_url),
                title=title,
                discovered_time=utc_now(),
                posted_time=published_at,
                feedparser_parsed=entry,
            )
            self.logger.info(f"   new post {post_id} {title}")
            self.cache_set(post_id, value.to_dict())

        self.set_last_run()

    def post(self, post_id: str) -> Optional[feed.FeedItem]:
        cached = self.cache_get(post_id)
        if not cached:
            return None
        return RssPost(**cached)
