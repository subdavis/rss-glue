import html
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import utc_now

html_template = """
<article>
    <div>{content}</div>
    <p>
        By <a href="https://reddit.com/u/{author}">u/{author}</a>
        <span style="padding: 1em">⬆️ {score}</span>
    </p>
</article>
"""


@dataclass
class RedditPost(feed.FeedItem):
    """
    A Reddit post is a single post from Reddit JSON API
    """

    post_data: dict

    def score(self) -> float:
        return self.post_data.get("score", 1)

    def render(self):
        # There are a few different types of reddit posts, signified by the "post_hint" field
        # self, link, image, video, rich:video, and hosted:video
        html_content = ""
        if self.post_data.get("post_hint", None):
            if self.post_data.get("post_hint") == "image":
                html_content = f'<img src="{self.post_data.get("url_overridden_by_dest")}" style="max-width: 100%; height: auto;" />'
            elif self.post_data.get("post_hint") == "link":
                html_content = f'<a href="{self.post_data.get("url")}">{self.post_data.get("url")}</a>'
            elif self.post_data.get("post_hint") == "rich:video":
                html_content = (
                    f'<video src="{self.post_data.get("url")}" controls></video>'
                )
            elif self.post_data.get("post_hint") == "self":
                html_content = html.unescape(self.post_data.get("selftext_html"))
            else:
                html_content = f'<a href="{self.post_data.get("url")}">{self.post_data.get("url")}</a>'
        elif self.post_data.get("selftext_html"):
            html_content = html.unescape(self.post_data.get("selftext_html"))
        else:
            html_content = (
                f'<a href="{self.post_data.get("url")}">{self.post_data.get("url")}</a>'
            )

        return html_template.format(
            author=self.author,
            posted_time=self.posted_time.strftime(utils.human_strftime),
            score=self.score(),
            content=html_content,
        )


class RedditFeed(feed.ScheduleFeed):
    """
    A Reddit feed is a feed of posts via the Reddit JSON API
    """

    subreddit: str
    url: str

    def __init__(self, url: str, schedule: str = "0 * * * *"):
        if not ".json" in url:
            raise ValueError("JSON endpoint expected")
        self.subreddit = url.split("/")[4]
        self.url = url
        self.title = f"r/{self.subreddit}"
        self.author = "Redditors"
        self.origin_url = f"https://www.reddit.com/r/{self.subreddit}"
        super().__init__(schedule=schedule)

    @property
    def namespace(self):
        # TODO this needs to differentiate between top/hot/new/etc and time periods
        return f"reddit_{self.subreddit}"

    def update(self, force: bool = False) -> int:
        if not self.needs_update(force):
            return 0

        # Fetch the posts from the Reddit API
        # and store them in the cache
        new_posts = []

        response = requests.get(self.url)
        response.raise_for_status()
        posts = response.json().get("data", {}).get("children", [])
        for post in posts:
            post_data = post.get("data", {})
            post_id = post_data.get("id")
            if self.cache_get(post_id):
                continue

            created_time_epoch = post_data.get("created_utc")
            created_time = datetime.fromtimestamp(created_time_epoch, tz=timezone.utc)
            value = RedditPost(
                version=0,
                namespace=self.namespace,
                id=post_id,
                post_data=post_data,
                author=post_data.get("author"),
                title=post_data.get("title"),
                posted_time=created_time,
                discovered_time=utc_now(),
                origin_url=post_data.get("url"),
            )
            self.cache_set(post_id, value.to_dict())
            new_posts.append(value)
        self.set_last_run()
        return len(new_posts)

    def posts(self) -> list[feed.FeedItem]:
        posts = super().posts()
        return posts

    def post(self, post_id: str):
        cached = self.cache_get(post_id)
        if not cached:
            return None
        return RedditPost(**cached)