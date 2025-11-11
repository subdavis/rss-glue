import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import utc_now

html_template = utils.load_template("reddit_post.html.jinja")


@dataclass
class RedditPost(feed.FeedItem):
    """
    A Reddit post is a single post from Reddit JSON API
    """

    post_data: dict

    def score(self) -> float:
        return self.post_data.get("score", 1)

    def render(self):
        # Extract data from post_data
        post_hint = self.post_data.get("post_hint")

        # Get oembed data for rich videos
        oembed = None
        if post_hint == "rich:video":
            oembed = self.post_data.get("media", {}).get("oembed")

        # Get fallback URL for hosted videos
        fallback_url = None
        if post_hint == "hosted:video":
            fallback_url = (
                self.post_data.get("media", {}).get("reddit_video", {}).get("fallback_url")
            )

        return html_template.render(
            author=self.author,
            score=self.score(),
            url=self.post_data.get("url"),
            selftext_html=(
                html.unescape(self.post_data.get("selftext_html", ""))
                if self.post_data.get("selftext_html")
                else None
            ),
            post_hint=post_hint,
            url_overridden_by_dest=self.post_data.get("url_overridden_by_dest"),
            oembed=oembed,
            fallback_url=fallback_url,
        )


class RedditFeed(feed.ThrottleFeed):
    """
    A Reddit feed is a feed of posts via the Reddit JSON API
    """

    subreddit: str
    url: str
    post_cls: type[RedditPost] = RedditPost
    name: str = "reddit"

    def __init__(self, url: str, interval: timedelta = timedelta(days=1)):
        if not ".json" in url:
            raise ValueError("JSON endpoint expected")
        self.subreddit = url.split("/")[4]
        self.url = url
        self.title = f"r/{self.subreddit}"
        self.author = "Redditors"
        self.origin_url = f"https://www.reddit.com/r/{self.subreddit}"
        super().__init__(interval=interval)

    @property
    def namespace(self):
        # TODO this needs to differentiate between top/hot/new/etc and time periods
        return f"reddit_{self.subreddit}"

    def update(self):
        # Fetch the posts from the Reddit API
        # and store them in the cache
        session = utils.make_browser_session()
        response = session.get(self.url)
        response.raise_for_status()
        posts = response.json().get("data", {}).get("children", [])
        for post in posts:
            post_data = post.get("data", {})
            post_id = post_data.get("id")
            if self.cache_get(post_id):
                continue

            created_time_epoch = post_data.get("created_utc")
            created_time = datetime.fromtimestamp(created_time_epoch, tz=timezone.utc)
            permalink = urljoin("https://www.reddit.com", post_data.get("permalink", ""))
            value = self.post_cls(
                version=0,
                namespace=self.namespace,
                id=post_id,
                post_data=post_data,
                author=post_data.get("author"),
                title=post_data.get("title"),
                posted_time=created_time,
                discovered_time=utc_now(),
                origin_url=permalink,
                enclosure=None,
            )
            self.logger.info(f"Adding post {value.id}")
            self.cache_set(post_id, value.to_dict())

        self.set_last_run()
