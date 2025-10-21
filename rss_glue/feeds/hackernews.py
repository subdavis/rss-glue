from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import utc_now

html_template = """
<article>
    <div><a href="{url}">{title}</a></div>
    <p>
        By <a href="https://news.ycombinator.com/user?id={author}">{author}</a>
        <span style="padding: 1em">⬆️ {score}</span>
        <span style="padding: 1em">💬 {descendants}</span>
        <span><a href="{comments_url}">[comments]</a></span>
    </p>
</article>
"""


@dataclass
class HackerNewsPost(feed.FeedItem):
    """
    A Hacker News post is a single story from the Hacker News API
    """

    story_data: dict

    def score(self) -> float:
        return self.story_data.get("score", 1)

    def render(self):
        url = self.story_data.get("url", "")
        title = self.story_data.get("title", "")
        author = self.story_data.get("by", "unknown")
        score = self.story_data.get("score", 0)
        descendants = self.story_data.get("descendants", 0)
        story_id = self.story_data.get("id")
        comments_url = f"https://news.ycombinator.com/item?id={story_id}"

        # If there's no URL, it's a text post (Ask HN, etc.)
        if not url:
            url = comments_url

        return html_template.format(
            url=url,
            title=title,
            author=author,
            score=score,
            descendants=descendants,
            comments_url=comments_url,
        )


class HackerNewsFeed(feed.ThrottleFeed):
    """
    A Hacker News feed is a feed of stories via the Hacker News API.
    Supports 'top', 'new', and 'best' story feeds.
    """

    feed_type: str
    url: str
    post_cls: type[HackerNewsPost] = HackerNewsPost
    name: str = "hackernews"

    def __init__(self, feed_type: str = "top", interval: timedelta = timedelta(hours=1)):
        if feed_type not in ["top", "new", "best"]:
            raise ValueError(f"Invalid feed type: {feed_type}. Must be 'top', 'new', or 'best'")

        self.feed_type = feed_type
        self.url = f"https://hacker-news.firebaseio.com/v0/{feed_type}stories.json"
        self.title = f"Hacker News - {feed_type.capitalize()}"
        self.author = "Hacker News Community"
        self.origin_url = "https://news.ycombinator.com"
        super().__init__(interval=interval)

    @property
    def namespace(self):
        return f"hackernews_{self.feed_type}"

    def update(self, force: bool = False):
        if not self.needs_update(force):
            return

        # Fetch the story IDs from the Hacker News API
        session = utils.make_browser_session()
        response = session.get(self.url)
        response.raise_for_status()
        story_ids = response.json()

        # Limit to first 30 stories to avoid too many API calls
        story_ids = story_ids[:30]

        for story_id in story_ids:
            # Check if we already have this story
            if self.cache_get(str(story_id)):
                continue

            # Fetch individual story details
            story_url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            story_response = session.get(story_url)
            story_response.raise_for_status()
            story_data = story_response.json()

            # Skip if deleted or dead
            if story_data.get("deleted") or story_data.get("dead"):
                continue

            # Skip non-story items (comments, jobs, etc.)
            if story_data.get("type") != "story":
                continue

            created_time_epoch = story_data.get("time")
            created_time = datetime.fromtimestamp(created_time_epoch, tz=timezone.utc)

            value = self.post_cls(
                version=0,
                namespace=self.namespace,
                id=str(story_id),
                story_data=story_data,
                author=story_data.get("by", "unknown"),
                title=story_data.get("title", ""),
                posted_time=created_time,
                discovered_time=utc_now(),
                origin_url=story_data.get(
                    "url", f"https://news.ycombinator.com/item?id={story_id}"
                ),
            )
            self.logger.info(f"Adding story {value.id}: {value.title}")
            self.cache_set(str(story_id), value.to_dict())

        self.set_last_run()

    def posts(self) -> list[feed.FeedItem]:
        posts = super().posts()
        return posts

    def post(self, post_id: str):
        cached = self.cache_get(post_id)
        if not cached:
            return None
        return self.post_cls(**cached)
