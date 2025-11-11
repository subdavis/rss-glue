import html
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from rss_glue import utils
from rss_glue.feeds import feed
from rss_glue.resources import utc_now

html_template = utils.load_template("facebook_post.html.jinja")


@dataclass
class FacebookGroupPost(feed.FeedItem):
    """
    A Facebook group post from the scrapecreators API
    """

    post_data: dict

    def reactions(self) -> int:
        return self.post_data.get("reactionCount", 0)

    def comments(self) -> int:
        return self.post_data.get("commentCount", 0)

    def video_views(self) -> Optional[int]:
        return self.post_data.get("videoViewCount")

    def score(self) -> float:
        """Use reaction count as the score for sorting"""
        return float(self.reactions())

    def render(self):
        # Extract text if available
        text = self.post_data.get("text", "")
        text_html = html.escape(text) if text else None

        # Build author info
        author_info = self.post_data.get("author", {})
        author_name = author_info.get("name", self.author)
        author_url = (
            author_info.get("url", self.origin_url)
            if isinstance(author_info, dict)
            else self.origin_url
        )

        return html_template.render(
            text=text_html,
            images=self.post_data.get("images", []),
            image=self.post_data.get("image"),
            video_details=self.post_data.get("videoDetails"),
            author=html.escape(author_name),
            author_url=author_url,
            reactions=self.reactions(),
            comments=self.comments(),
            video_views=self.video_views(),
        )


class FacebookGroupFeed(feed.ThrottleFeed):
    """
    A Facebook group/page feed via the scrapecreators API
    """

    url: str
    group_id: str
    api_key: str
    post_cls: type[FacebookGroupPost] = FacebookGroupPost
    name: str = "facebook_group"

    def __init__(
        self,
        origin_url: str,
        api_key: str,
        title: Optional[str] = None,
        interval: timedelta = timedelta(hours=6),
    ):
        self.origin_url = origin_url
        self.api_key = api_key
        self.author = "Facebook"
        self.group_id = urlparse(self.origin_url).path.strip("/").split("/")[-1]
        self.title = title or f"Facebook Group: {self.group_id}"
        super().__init__(interval=interval)

    @property
    def namespace(self):
        # Use group ID or page ID from the URL as namespace
        return f"{self.name}_{self.group_id}"

    def update(self):
        # Fetch posts from the scrapecreators API
        session = utils.make_browser_session()
        headers = {"x-api-key": self.api_key}
        response = session.get(
            "https://api.scrapecreators.com/v1/facebook/group/posts",
            headers=headers,
            params={"url": self.origin_url, "sort_by": "CHRONOLOGICAL"},
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            self.logger.warning(f"API request not successful: {data}")
            return

        posts = data.get("posts", [])
        for post_data in posts:
            post_id = post_data.get("id")
            if not post_id:
                self.logger.warning("Post missing ID, skipping")
                continue

            if self.cache_get(post_id):
                continue

            # Extract timestamp
            publish_time = post_data.get("publishTime")
            if publish_time:
                created_time = datetime.fromtimestamp(publish_time, tz=timezone.utc)
            else:
                created_time = utc_now()

            # Extract author
            author = "Unknown"
            if author_data := post_data.get("author"):
                if isinstance(author_data, dict):
                    author = author_data.get("name", "Unknown")

            # Extract title from text
            title = "Facebook Group Post"
            if text := post_data.get("text"):
                # Use first line or first 100 chars as title
                title = text.split("\n")[0][:100]
            elif not text and post_data.get("image"):
                title = "Photo Post"
            elif not text and post_data.get("videoDetails"):
                title = "Video Post"

            # Get post URL
            post_url = post_data.get("url", self.origin_url)

            value = self.post_cls(
                version=0,
                namespace=self.namespace,
                id=post_id,
                post_data=post_data,
                author=author,
                title=title,
                posted_time=created_time,
                discovered_time=utc_now(),
                origin_url=post_url,
                enclosure=None,
            )
            self.logger.info(f"Adding post {value.id}")
            self.cache_set(post_id, value.to_dict())

        self.set_last_run()
